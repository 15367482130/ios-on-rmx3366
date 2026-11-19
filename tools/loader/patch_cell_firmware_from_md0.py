#!/usr/bin/env python3
"""Make instantnoodle_cell.c read modem firmware from the appended tail of md0.

Video reference (b23.tv/oOzJVT0, SDX55 external modem on XNU): firmware images
are packed into RAM instead of being read from the phone's UFS partitions.
That is exactly what we need on RMX3366, where the UEFI exposes no UFS
partition handles, so /dev/rufs_modem_a never appears.

We appended the phone's real firmware images to the END of system.apfs:
  modem.img  at LBA 604668 (FAT16, 195 MB, with image/sdx55m/*.mbn)
  efs1       at LBA 654588
  efs2       at LBA 655100
  efsc       at LBA 655612
system.apfs becomes /dev/md0 at boot (the resident image = root).

When /dev/rufs_<name> cannot be opened, fall back to /dev/md0 at an offset
given by boot-arg modem_fw_base (in 4096-byte blocks). The upper layers
(FAT16 mount, Sahara, QRTR) are untouched.
"""
import io

P = "/root/work/instantnoodle-xnu/xnu-src/xnu-8796.121.2/bsd/dev/instantnoodle_cell.c"
s = io.open(P, encoding="utf-8").read()

# 1) state: base block for md0 fallback, and per-part extra offset
old = "static const char *fw_partition;\n"
new = ("static const char *fw_partition;\n"
       "/* modem_fw_base=: LBA in /dev/md0 where the appended firmware blob starts.\n"
       " * 0 = disabled (read /dev/rufs_* as before). The blob holds modem.img, efs1,\n"
       " * efs2, efsc back to back, each 4096-byte aligned; see firmware-offsets.json. */\n"
       "static uint64_t md0_fw_base_blocks;\n"
       "static int md0_fallback_used;\n")
assert s.count(old) == 1
s = s.replace(old, new, 1)

# 2) struct: add base offset in blocks (0 = a real partition, no shift)
old = """\tuint8_t *cache;
\tuint64_t cached_at, bytes;
\tbool have;
} cell_parts[CELL_PARTS];"""
new = """\tuint8_t *cache;
\tuint64_t cached_at, bytes;
\tuint64_t base_blocks;           /* md0 fallback: starting LBA of this image; 0 = real partition */
\tbool have;
} cell_parts[CELL_PARTS];"""
assert s.count(old) == 1
s = s.replace(old, new, 1)

# 3) cell_part(): when /dev/rufs fails, try /dev/md0 at the appended offset
old = """\tif (vnode_open(path, FREAD, 0, 0, &p->vp, vfs_context_kernel()) != 0) {
\t\tp->vp = NULL;
\t\treturn NULL;
\t}
\tstrlcpy(p->name, name, sizeof(p->name));
\tp->have = false;
\t{
\t\tuint64_t blocks = 0;
\t\tuint32_t size = 0;

\t\tif (VNOP_IOCTL(p->vp, DKIOCGETBLOCKCOUNT, (caddr_t)&blocks, 0, vfs_context_kernel()) == 0 &&
\t\t    VNOP_IOCTL(p->vp, DKIOCGETBLOCKSIZE, (caddr_t)&size, 0, vfs_context_kernel()) == 0) {
\t\t\tp->bytes = blocks * size;
\t\t}
\t}
\treturn p;"""
new = """\tif (vnode_open(path, FREAD, 0, 0, &p->vp, vfs_context_kernel()) != 0) {
\t\t/* The phone's UEFI may expose no UFS partition handles. Read the
\t\t * firmware we packed at the tail of the resident system image instead. */
\t\tuint64_t lba = 0;
\t\tuint64_t len = 0;

\t\tif (md0_fw_base_blocks == 0) {
\t\t\tp->vp = NULL;
\t\t\treturn NULL;
\t\t}
\t\tif (strcmp(name, fw_partition) == 0) {
\t\t\tlba = md0_fw_base_blocks;         /* modem.img */
\t\t\tlen = 204472320ULL;
\t\t} else if (strcmp(name, "mdm1m9kefs1") == 0) {
\t\t\tlba = md0_fw_base_blocks + 654588 - 604668;
\t\t\tlen = 2097152ULL;
\t\t} else if (strcmp(name, "mdm1m9kefs2") == 0) {
\t\t\tlba = md0_fw_base_blocks + 655100 - 604668;
\t\t\tlen = 2097152ULL;
\t\t} else if (strcmp(name, "mdm1m9kefs3") == 0 || strcmp(name, "mdm1m9kefsc") == 0) {
\t\t\tlba = md0_fw_base_blocks + 655612 - 604668;
\t\t\tlen = 4096ULL;
\t\t} else {
\t\t\tp->vp = NULL;
\t\t\treturn NULL;
\t\t}
\t\tif (vnode_open("/dev/rmd0", FREAD, 0, 0, &p->vp, vfs_context_kernel()) != 0) {
\t\t\tp->vp = NULL;
\t\t\treturn NULL;
\t\t}
\t\tp->base_blocks = lba;
\t\tp->bytes = len;
\t\tmd0_fallback_used = 1;
\t\tsay("modem: %s: no %s; using /dev/rmd0 at LBA %llu (%llu bytes)\\n", name, path, lba, len);
\t} else {
\t\tuint64_t blocks = 0;
\t\tuint32_t size = 0;

\t\tif (VNOP_IOCTL(p->vp, DKIOCGETBLOCKCOUNT, (caddr_t)&blocks, 0, vfs_context_kernel()) == 0 &&
\t\t    VNOP_IOCTL(p->vp, DKIOCGETBLOCKSIZE, (caddr_t)&size, 0, vfs_context_kernel()) == 0) {
\t\t\tp->bytes = blocks * size;
\t\t}
\t}
\tstrlcpy(p->name, name, sizeof(p->name));
\tp->have = false;
\treturn p;"""
assert s.count(old) == 1, "cell_part body"
s = s.replace(old, new, 1)

# 4) cell_part_read(): add base_blocks to the byte offset
old = """\t\t\tint resid = 0, error = vn_rdwr(UIO_READ, p->vp, (caddr_t)p->cache, CELL_CACHE, (off_t)base, UIO_SYSSPACE, IO_NOAUTH | IO_NOCACHE, kauth_cred_get(), &resid, current_proc());"""
new = """\t\t\tint resid = 0, error = vn_rdwr(UIO_READ, p->vp, (caddr_t)p->cache, CELL_CACHE,
\t\t\t    (off_t)(base + (p->base_blocks << 12)), UIO_SYSSPACE, IO_NOAUTH | IO_NOCACHE,
\t\t\t    kauth_cred_get(), &resid, current_proc());"""
assert s.count(old) == 1, "vn_rdwr call"
s = s.replace(old, new, 1)

# 5) parse boot-arg in the init function, next to modem_fw
old = """\tcell_arg("modem_secs", &sahara_seconds, sizeof(sahara_seconds));"""
new = """\tcell_arg("modem_secs", &sahara_seconds, sizeof(sahara_seconds));
\tcell_arg("modem_fw_base", &md0_fw_base_blocks, sizeof(md0_fw_base_blocks));
\tif (md0_fw_base_blocks != 0) {
\t\tsay("modem: firmware from /dev/md0 at LBA %llu (packed in the system image)\\n", md0_fw_base_blocks);
\t}"""
assert s.count(old) == 1, "bootarg anchor"
s = s.replace(old, new, 1)

io.open(P, "w", encoding="utf-8").write(s)
print("cell firmware-from-md0 patch applied")
