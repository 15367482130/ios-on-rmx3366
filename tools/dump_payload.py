#!/usr/bin/env python3
"""Print the entries of an XNUP payload (name, size, cmdline)."""
import sys, struct

for path in sys.argv[1:]:
    d = open(path, "rb").read()
    magic, size = struct.unpack_from("<II", d, 0)
    assert magic == 0x50554E58, hex(magic)
    off, end = 8, 8 + size
    print("###", path, size + 8, "bytes")
    while off + 24 <= end:
        name = d[off:off + 16].split(b"\0")[0].decode("latin1")
        n, res = struct.unpack_from("<II", d, off + 16)
        if not name:
            break
        data = d[off + 24:off + 24 + n]
        if name == "cmdline":
            print(f"  {name:8s} {n:9d}  {data.decode('latin1', 'replace').strip()}")
        else:
            print(f"  {name:8s} {n:9d}")
        off += 24 + n + (-n % 16)
