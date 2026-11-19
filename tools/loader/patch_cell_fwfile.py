#!/usr/bin/env python3
"""Adapt cell firmware storage: when /dev/rufs_modem_a is unavailable
(this realme RMX3366's UEFI gives no UFS partition info), fall back to
reading the firmware FAT16 image from the ramdisk file /redwood/fw/modem.img.

Only the path selection in cell_part() changes; the read path (vn_rdwr with
byte offsets) works identically on a regular file and on a char device.
The image was pulled read-only from this phone's modem partition and is a
valid FAT16 (bps=4096, "FAT16" at offset 54) -- exactly what fat_mount wants.
"""
import io

P = "/root/work/instantnoodle-xnu/xnu-src/xnu-8796.121.2/bsd/dev/instantnoodle_cell.c"
s = io.open(P, encoding="utf-8").read()

old = '''\tsnprintf(path, sizeof(path), "/dev/rufs_%s", name);
\tif (p->cache == NULL && (p->cache = kalloc_data(CELL_CACHE, Z_WAITOK | Z_ZERO)) == NULL) {
\t\treturn NULL;
\t}
\tif (vnode_open(path, FREAD, 0, 0, &p->vp, vfs_context_kernel()) != 0) {
\t\tp->vp = NULL;
\t\treturn NULL;
\t}
'''
new = '''\tsnprintf(path, sizeof(path), "/dev/rufs_%s", name);
\tif (p->cache == NULL && (p->cache = kalloc_data(CELL_CACHE, Z_WAITOK | Z_ZERO)) == NULL) {
\t\treturn NULL;
\t}
\tif (vnode_open(path, FREAD, 0, 0, &p->vp, vfs_context_kernel()) != 0) {
\t\t/* RMX3366: this UEFI exposes no UFS partition table, so /dev/rufs_*
\t\t * is absent. Fall back to the FAT16 firmware image pulled from this
\t\t * phone's modem partition and carried in the ramdisk. vn_rdwr below
\t\t * reads regular files by byte offset exactly like the char device. */
\t\tp->vp = NULL;
\t\tif (vnode_open("/redwood/fw/modem.img", FREAD, 0, 0, &p->vp, vfs_context_kernel()) != 0) {
\t\t\tp->vp = NULL;
\t\t\treturn NULL;
\t\t}
\t\tsay("modem: fw: %s is not a UFS device; reading /redwood/fw/modem.img\\n", name);
\t}
'''
assert old in s, "cell_part open anchor not found"
s = s.replace(old, new, 1)
io.open(P, "w", encoding="utf-8").write(s)
print("cell_part() firmware-file fallback applied")
