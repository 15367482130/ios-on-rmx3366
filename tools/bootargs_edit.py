"""Rewrite boot arguments inside a payload's cmdline entry (everything else untouched).

usage: _mkcmd.py in.bin out.bin OLD NEW [OLD NEW ...]

Only the "cmdline" entry is rebuilt, so kernel and ramdisk keep their bytes and the image
stays the same size; a payload whose cmdline grows past its padded slot would move every
entry after it, which is why the size is asserted to stay identical here.
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


src, dst = sys.argv[1], sys.argv[2]
rest = sys.argv[3:]
assert len(rest) % 2 == 0, "give pairs: old new [old new ...]"
pairs = list(zip(rest[0::2], rest[1::2]))

entries = parse(src)
out = []
for name, data in entries:
    if name == "cmdline":
        text = data.split(b"\0")[0].decode()
        for old, new in pairs:
            assert old in text, "cmdline has no %r" % old
            text = text.replace(old, new)
        if len(text) + 1 != len(data):
            raise SystemExit("cmdline length changed (%d -> %d): would move every entry after it"
                             % (len(data), len(text) + 1))
        print("cmdline:", text)
        data = text.encode() + b"\0"
    out.append((name, data))
blob = build(out)
assert len(blob) == len(open(src, "rb").read()), "payload size changed"
open(dst, "wb").write(blob)
print(dst, "bytes:", len(blob))
