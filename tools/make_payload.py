#!/usr/bin/env python3
"""Build an XNUP payload: kernel + ramdisk + cmdline.

usage: make_payload.py -o out.bin --kernel k.bin --ramdisk r.apfs --cmdline "..."
       make_payload.py -o out.bin --from old.bin          (rewrite cmdline of an existing payload)

Format (xnuloader/mkpayload.py): u32 magic "XNUP", u32 size, then entries
char name[16], u32 size, u32 reserved, data padded to 16 bytes.
"""
import argparse
import struct

MAGIC = 0x50554E58


def parse(path):
    d = open(path, "rb").read()
    magic, size = struct.unpack_from("<II", d, 0)
    assert magic == MAGIC, hex(magic)
    off, end = 8, 8 + size
    entries = []
    while off + 24 <= end:
        name = d[off:off + 16].split(b"\0")[0].decode("latin1")
        n, _res = struct.unpack_from("<II", d, off + 16)
        if not name:
            break
        entries.append((name, d[off + 24:off + 24 + n]))
        off += 24 + n + (-n % 16)
    return entries


def build(entries):
    body = b""
    for name, data in entries:
        body += struct.pack("<16sII", name.encode(), len(data), 0)
        body += data + b"\0" * (-len(data) % 16)
    body += b"\0" * 24
    return struct.pack("<II", MAGIC, len(body)) + body


ap = argparse.ArgumentParser()
ap.add_argument("-o", "--output", required=True)
ap.add_argument("--from", dest="src")
ap.add_argument("--kernel")
ap.add_argument("--ramdisk")
ap.add_argument("--cmdline")
ap.add_argument("--drop", action="append", default=[])
a = ap.parse_args()

if a.src:
    entries = parse(a.src)
else:
    entries = []
    if a.kernel:
        entries.append(("kernel", open(a.kernel, "rb").read()))
    if a.ramdisk:
        entries.append(("ramdisk", open(a.ramdisk, "rb").read()))

out = []
replaced = {"kernel": a.kernel, "ramdisk": a.ramdisk}
for name, data in entries:
    if a.drop and name in a.drop:
        continue
    if replaced.get(name):
        data = open(replaced[name], "rb").read()
    if name == "cmdline" and a.cmdline:
        data = a.cmdline.encode() + b"\0"
    out.append((name, data))
if a.cmdline and not any(n == "cmdline" for n, _ in out):
    out.append(("cmdline", a.cmdline.encode() + b"\0"))

open(a.output, "wb").write(build(out))
print(a.output, "entries:", [n for n, _ in out], "bytes:", len(build(out)))
