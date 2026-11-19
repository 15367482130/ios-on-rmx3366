"""Remove whole tokens from a payload's cmdline entry, repacking the container.

Why not just set the value to 0: the kernel decides some defaults on the *presence*
of the argument, not its value -- `mdp_shots` is 2000 ms in a run that has
`loader_return_after=` (MiniIOMobileFramebuffer.cpp), which costs the presenter
10-25 ms every 2 s.  A boot that is meant to last has to lose the token itself.

The container (see make_payload.py / loader.c): "XNUP", total size, then entries
of {char name[16]; u32 length; u32 reserved; body; zero pad to 16}.  The cmdline
is the last entry, so a shorter one only needs its own length and the total fixed.

usage: _rmcmd.py in.bin out.bin token [token ...]
       (a token matches at a word boundary; the space before it goes too)
"""
import struct
import sys


def parse(d):
    magic, total = struct.unpack_from("<II", d, 0)
    assert magic == 0x50554E58, "not a XNUP payload: %08x" % magic
    entries = []
    off = 8
    while off + 24 <= total:
        name = d[off:off + 16].split(b"\0")[0].decode("latin1")
        if not name:
            break
        n, _res = struct.unpack_from("<II", d, off + 16)
        body = d[off + 24:off + 24 + n]
        entries.append([name, body])
        off += 24 + n + (-n % 16)
    return entries, total


def build(entries):
    out = bytearray(b"\0" * 8)
    for name, body in entries:
        out += name.encode("latin1").ljust(16, b"\0")
        out += struct.pack("<II", len(body), 0)
        out += body
        out += b"\0" * (-len(body) % 16)
    struct.pack_into("<II", out, 0, 0x50554E58, len(out) - 8)   # the size counts from offset 8
    return bytes(out)


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    src, dst, tokens = sys.argv[1], sys.argv[2], sys.argv[3:]

    d = open(src, "rb").read()
    entries, total = parse(d)
    names = [e[0] for e in entries]
    print("entries:", names)
    assert "cmdline" in names, "no cmdline entry"
    assert names[-1] == "cmdline", "cmdline is not the last entry (%s): tell me, the offsets shift" % names[-1]

    idx = names.index("cmdline")
    raw = entries[idx][1]
    # the entry carries NUL padding past the string: edit the string, keep the padding
    body = raw.split(b"\0")[0]
    pad = raw[len(body):]
    line = body.decode("latin1")
    before = line
    for tok in tokens:
        # a whole word, with the space in front of it
        for cand in (" " + tok, tok):
            if cand in line:
                line = line.replace(cand, "", 1)
                break
        else:
            sys.exit("token not in cmdline: %r" % tok)
    print("cmdline: %d -> %d bytes" % (len(before), len(line)))
    print("removed:", " ".join(tokens))
    assert line.strip(), "cmdline became empty"
    assert "\0" not in line, "cmdline has a NUL"
    entries[idx][1] = line.encode("latin1")

    out = build(entries)
    open(dst, "wb").write(out)
    print("%s: %d bytes (was %d)" % (dst, len(out), len(d)))

    # the parts that are not the cmdline must be untouched, byte for byte
    a, b = parse(d), parse(out)
    for (na, ba), (nb, bb) in zip(a[0], b[0]):
        assert na == nb
        if na != "cmdline":
            assert ba == bb, "entry %s changed!" % na
    print("kernel and ramdisk identical; ok")


if __name__ == "__main__":
    main()
