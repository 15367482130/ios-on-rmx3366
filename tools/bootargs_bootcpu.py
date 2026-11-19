"""Rewrite only the cmdline of a payload, to move the kernel onto another core.

Why: this loader instance already started the kernel once, and Qualcomm's PSCI answers
-4 (INVALID_PARAMETERS) to a second CPU_ON of the same core, so a staged system volume
cannot be run a second time.  "bootcpu=N" makes the loader pick the core; with the core
the loader itself runs on (MPIDR 0), the loader takes its local jump path and no PSCI
call is involved at all -- the staged image runs without a cold reset.

usage: _mkcpu0.py <in.bin> <out.bin> <core>
"""
import struct
import sys

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


src, dst, core = sys.argv[1], sys.argv[2], sys.argv[3]
entries = parse(src)
out = []
for name, data in entries:
    if name == "cmdline":
        text = data.split(b"\0")[0].decode()
        assert " bootcpu=" in " " + text, "no bootcpu in cmdline"
        parts = [p for p in text.split(" ") if not p.startswith("bootcpu=")]
        parts.append("bootcpu=" + core)
        text = " ".join(parts)
        data = text.encode() + b"\0"
        print("cmdline:", text)
    out.append((name, data))
open(dst, "wb").write(build(out))
print(dst, "bytes:", len(build(out)))
