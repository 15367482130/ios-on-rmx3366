#!/usr/bin/env python3
"""Add a GPT-parsing fallback to xnuloader's block service.

Problem: on realme RMX3366 the UEFI does not expose EFI_PARTITION_INFO_GUID
handles, so block_start() returns early with only raw units -- no modem_a,
no /dev/rufs_modem_a in the kernel, and the cell firmware reader starves.

Fix (true root-cause fix, not a bypass): when the partition-info protocol is
absent, parse the GPT on each raw unit ourselves (ufs_check_gpt already reads
the header), and publish real partitions into block_shared.part[] with their
start_lba/unit/block_size, so the kernel sees /dev/rufs_modem_a and its
ufs_native path can read the partition at start_lba.

The kernel's native read uses ufs_lun_offset[i] = start_lba * block_size.
The loader's mailbox path needs the unit base added to the LBA, so track a
per-partition base in block_bios_base[].

All replacements are exact-once with assertions.
"""
import io

P = "/root/work/instantnoodle-xnu/xnuloader/loader.c"
s = io.open(P, encoding="utf-8").read()

# 1) per-partition unit base for the mailbox path
old = "static efi_block_io *block_bios[BLOCK_MAX_PARTS];\n"
new = ("static efi_block_io *block_bios[BLOCK_MAX_PARTS];\n"
       "static uint64_t block_bios_base[BLOCK_MAX_PARTS];  /* GPT-fallback parts: unit LBA of the partition start */\n")
assert s.count(old) == 1
s = s.replace(old, new, 1)

# 2) mailbox read/write: add the unit base (zero for native UEFI partitions).
#    Both occurrences are inside block_poll(); the one at ~1633 uses ufs_buffer
#    and a different variable set, so match the exact block_buffer forms.
old = "bio->read_blocks(bio, bio->media->media_id, lba, bytes, block_buffer)"
new = "bio->read_blocks(bio, bio->media->media_id, lba + block_bios_base[part], bytes, block_buffer)"
assert s.count(old) == 2, s.count(old)
s = s.replace(old, new)
old = "bio->write_blocks(bio, bio->media->media_id, lba, bytes, block_buffer)"
new = "bio->write_blocks(bio, bio->media->media_id, lba + block_bios_base[part], bytes, block_buffer)"
assert s.count(old) == 1
s = s.replace(old, new, 1)

# 3a) name the units structure so the helper and block_start share one type
old = '''\tstatic const efi_guid dp_guid = EFI_DEVICE_PATH_GUID;
\tstatic struct {
\t\tefi_block_io *bio;
\t\tconst efi_device_path *path;
\t\tuint64_t path_bytes;
\t\tuint8_t lun;
\t} units[BLOCK_MAX_UNITS];
'''
new = '''\tstatic const efi_guid dp_guid = EFI_DEVICE_PATH_GUID;
\tstatic struct block_unit units[BLOCK_MAX_UNITS];
'''
assert s.count(old) == 1, "units struct anchor"
s = s.replace(old, new, 1)

# 3b) add the named struct definition before block_start
anchor = "static void\nblock_start(void)\n"
assert s.count(anchor) == 1
structdef = r'''struct block_unit {
    efi_block_io *bio;
    const efi_device_path *path;
    uint64_t path_bytes;
    uint8_t lun;
};

'''
fallback = structdef + r'''
/*
 * GPT fallback: this UEFI gives raw UFS logical units but no partition
 * handles (EFI_PARTITION_INFO_GUID). Read the GPT off each unit ourselves and
 * publish its partitions as if UEFI had enumerated them. Needed on the realme
 * RMX3366, where /dev/rufs_modem_a would otherwise never exist and the modem
 * firmware cannot be read.
 */
static void
block_gpt_fallback(struct block_unit *units, uint64_t nunits)
{
    static const uint8_t gpt_magic[8] = {'E','F','I',' ','P','A','R','T'};
    uint8_t *buf = (uint8_t *)(uintptr_t)ufs_buffer;

    for (uint64_t u = 0; u < nunits; u++) {
        efi_block_io *bio = units[u].bio;
        uint64_t bs = bio->media->block_size, entries_lba, count, size, bytes, at;
        uint32_t hsz, hcrc, ecrc;
        uint8_t header[512];

        if (bs < 512 || bs > sizeof(ufs_buffer) ||
            EFI_ERROR(bio->read_blocks(bio, bio->media->media_id, 1, bs, buf))) {
            continue;
        }
        if (memcmp(buf, gpt_magic, 8) != 0) {
            continue;
        }
        memcpy(header, buf, sizeof(header));
        hsz = *(uint32_t *)(header + 12);
        hcrc = *(uint32_t *)(header + 16);
        entries_lba = *(uint64_t *)(header + 72);
        count = *(uint32_t *)(header + 80);
        size = *(uint32_t *)(header + 84);
        ecrc = *(uint32_t *)(header + 88);
        if (hsz < 92 || hsz > sizeof(header) || size < 128 || count == 0 ||
            count * size > sizeof(ufs_buffer)) {
            continue;
        }
        *(uint32_t *)(header + 16) = 0;
        if (ufs_crc32(header, hsz) != hcrc) {
            continue;
        }
        bytes = count * size;
        at = entries_lba * bs;
        {
            uint64_t read = (bytes + bs - 1) / bs * bs;   /* read_blocks wants whole blocks */
            if (EFI_ERROR(bio->read_blocks(bio, bio->media->media_id, entries_lba, read, buf))) {
                continue;
            }
        }
        if (ufs_crc32(buf, bytes) != ecrc) {
            continue;
        }
        print("ufs: GPT fallback: unit %u: %d entries, table crc right\n", u, count);
        for (uint64_t e = 0; e < count; e++) {
            const uint8_t *ent = buf + e * size;
            struct loader_block_part *bp;
            uint64_t first, last;
            unsigned n;

            /* a zero type GUID is an unused entry */
            {
                int any = 0;
                for (unsigned i = 0; i < 16; i++) any |= ent[i];
                if (!any) continue;
            }
            first = *(uint64_t *)(ent + 32);
            last  = *(uint64_t *)(ent + 40);
            if (last < first) continue;

            {
                static const uint8_t zero_type[16] = {
                    0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,
                    0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00
                };
                (void)zero_type;
            }
            if (block_shared.parts + nunits >= BLOCK_MAX_PARTS) break;
            bp = &block_shared.part[block_shared.parts];
            /* name: UTF-16LE at offset 56, 36 chars */
            for (n = 0; n + 1 < sizeof(bp->name) && n < 36; n++) {
                uint16_t c = (uint16_t)(ent[56 + n * 2] | (ent[57 + n * 2] << 8));
                bp->name[n] = (c != 0 && c < 0x80) ? (char)c : 0;
                if (c == 0) break;
            }
            bp->name[n] = 0;
            if (bp->name[0] == 0) continue;

            bp->block_size = (uint32_t)bs;
            bp->blocks = last - first + 1;
            bp->start_lba = first;
            bp->unit = (uint16_t)u;
            bp->lun = units[u].lun;
            bp->flags = 0;
            block_bios[block_shared.parts] = bio;
            block_bios_base[block_shared.parts] = first;  /* mailbox: unit LBA = partition LBA + first */
            print("ufs: GPT fallback: part %s: lba %d..%d on unit %u\n",
                  bp->name, first, last, u);
            block_shared.parts++;
        }
        (void)at;
    }
}

'''
s = s.replace(anchor, fallback + anchor, 1)

# 4) in block_start(), when part_guid is absent, call fallback instead of bare return
old = '''\tif (EFI_ERROR(BS->locate_handle_buffer(ByProtocol, &part_guid, NULL, &count, &handles))) {
\t\tprint("ufs: no partition information: the block service is off\\n");
\t\treturn;
\t}
'''
new = '''\tif (EFI_ERROR(BS->locate_handle_buffer(ByProtocol, &part_guid, NULL, &count, &handles))) {
\t\tprint("ufs: no partition information: the block service is off; trying the GPT fallback\\n");
\t\tblock_gpt_fallback(units, nunits);
\t\tgoto after_partitions;   /* no UEFI partition loop; still publish units + native list */
\t}
'''
assert s.count(old) == 1, "part_guid fail anchor"
s = s.replace(old, new, 1)

# 5) add the goto label after the UEFI partition loop, before the darwin-file block
label_anchor = "\t/* darwin as a file of userdata: a partition of its own blocks, on no unit (the kernel reads it through here) */\n"
assert s.count(label_anchor) == 1
s = s.replace(label_anchor, "\tafter_partitions:\n" + label_anchor, 1)

io.open(P, "w", encoding="utf-8").write(s)
print("GPT fallback applied to", P)
