#!/usr/bin/env python3
"""Replace only the loader.efi bytes inside a working Android boot image.

Everything else (boot header, gzip'd BootShim+FD, DTB) is kept byte-identical
to the known-good base image, which avoids the packaging-parameter drift that
made freshly-built images fail to enumerate.

Why not just recompress the whole blob and rewrite the header: the header's
kernel_size (1817723) does not equal the real gzip stream length (1129718) --
it also covers the first 688005 bytes of the 690954-byte DTB that follows. A
rebuild that trusts kernel_size therefore cuts the DTB short (that is what this
script used to do: the tail came out 2949 bytes too short).

So: locate the gzip stream by inflating, keep the exact DTB tail, and pad the
recompressed stream to the original stream length. Every offset the bootloader
computes is then unchanged.

Usage:
  python replace_loader_in_bootimg.py <base.img> <new-loader.efi> <out.img>
"""
import hashlib
import struct
import sys
import zlib

base_path, loader_path, out_path = sys.argv[1:4]
d = open(base_path, "rb").read()
new_loader = open(loader_path, "rb").read()

assert d[:8] == b"ANDROID!", d[:8]
GZ = d.find(b"\x1f\x8b\x08", 0x800)
assert 0x800 <= GZ < 0x1000, hex(GZ)

# Inflate from the stream start to the end of the file: what the stream did not
# consume is the DTB, and is kept as is.
probe = zlib.decompressobj(16 + zlib.MAX_WBITS)
blob = probe.decompress(d[GZ:])
assert probe.eof, "base image: gzip stream never ends"
stream_len = len(d) - GZ - len(probe.unused_data)
tail = d[GZ + stream_len:]
print(f"gzip stream {stream_len} bytes at {hex(GZ)}, {len(blob)} bytes inflated, DTB {len(tail)} bytes")

# locate XNUP container inside the blob (after the 3 MB FD)
i = blob.find(b"XNUP", 0x300000 - 0x100)
assert i > 0
sz = struct.unpack_from("<I", blob, i + 4)[0]
assert 0 < sz < 0x100000, hex(sz)

off = i + 8
end = i + 8 + sz
entries = []
loader_off = loader_len = None
while off + 24 <= end:
    name = blob[off:off + 16].split(b"\0")[0].decode("latin1")
    n, _res = struct.unpack_from("<II", blob, off + 16)
    if not name:
        break
    entries.append((off, name, n))
    if name == "loader.efi":
        loader_off, loader_len = off + 24, n
    off += 24 + n + (-n % 16)

assert loader_off is not None, "no loader.efi entry"
print("base loader.efi:", loader_len, "bytes at", hex(loader_off))
print("new loader.efi:", len(new_loader), "bytes")

newblob = blob[:loader_off] + new_loader + b"\0" * (-len(new_loader) % 16) + \
    blob[loader_off + loader_len + (-loader_len % 16):]
assert len(newblob) == len(blob), "the blob changed size: the XNUP framing is off"

# Recompress as GZIP (wbits 31). zlib.compress() would emit a zlib stream
# (78 9c) and the boot shim would read garbage.
best = None
for level in (9, 8, 7, 6, 5, 4, 3, 2, 1):
    packer = zlib.compressobj(level, zlib.DEFLATED, 31)
    candidate = packer.compress(newblob) + packer.flush()
    if best is None or len(candidate) < len(best):
        best = candidate
    if len(candidate) <= stream_len:
        best = candidate
        break
assert best[:3] == b"\x1f\x8b\x08", best[:3]
assert len(best) <= stream_len, f"recompressed stream {len(best)} > original {stream_len}"

# Pad to the original stream length so every offset after it stays put. The
# padding sits after the gzip trailer and is never read.
padded = best + b"\0" * (stream_len - len(best))
out = d[:GZ] + padded + tail
assert len(out) == len(d), (len(out), len(d))

check = zlib.decompressobj(16 + zlib.MAX_WBITS)
back = check.decompress(out[GZ:])
assert check.eof and len(back) == len(newblob) and back[loader_off:loader_off + len(new_loader)] == new_loader

open(out_path, "wb").write(out)
print(f"wrote {out_path}: {len(out)} bytes (base {len(d)}), stream {len(best)} padded to {stream_len}")
print("base md5", hashlib.md5(d).hexdigest()[:12], "-> new", hashlib.md5(out).hexdigest()[:12])
