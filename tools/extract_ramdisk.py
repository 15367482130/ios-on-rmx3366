#!/usr/bin/env python3
"""Extract an APFS volume to a directory tree plus an mkapfs manifest.

usage: extract_ramdisk.py IMAGE OUTDIR [VOLUME]

The tree keeps what mkapfs needs from it (permission bits, symlink targets) and the
manifest keeps what a directory cannot hold on its own: the owner and group of every
entry (mobile is 501, not root).  Files are written decompressed: mkapfs -z compresses
them again where that makes them smaller.
"""
import os
import stat
import sys

APFS_TOOLS = "/root/work/instantnoodle-xnu/tools/apfs"
sys.path.insert(0, APFS_TOOLS)
import apfs  # noqa: E402


def main(argv):
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    image, outdir = argv[1], argv[2]
    want = argv[3] if len(argv) > 3 else None

    c = apfs.Container(image)
    v = apfs.pick_volume(c, want)
    hit = v.lookup("/")
    if hit is None:
        print("extract_ramdisk: no root directory", file=sys.stderr)
        return 1

    os.makedirs(outdir, exist_ok=True)
    manifest = []
    dirs = files = links = 0
    total = 0

    def owner_line(mode, uid, gid, path, target=None):
        line = "%o\t%d\t%d\t%s" % (mode, uid, gid, path)
        if target is not None:
            line += "\t" + target
        manifest.append(line)

    # the root itself is not in walk(): mkapfs makes it
    owner_line(stat.S_IFDIR | 0o755, 0, 0, "")

    for p, name, fid, dt in apfs.walk(v, hit[0], ""):
        ino = v.inode(fid)
        rel = p.lstrip("/")
        dest = os.path.join(outdir, rel)
        mode = ino.mode
        if ino.is_dir:
            os.makedirs(dest, exist_ok=True)
            dirs += 1
            owner_line(mode, ino.owner, ino.group, rel)
        elif ino.is_link:
            # a link's target may not exist here (dangling in the image): no chmod, and
            # lchown, since following the link is exactly what must not happen
            target = (ino.symlink_target_bytes() or b"").decode("utf-8", "surrogateescape")
            if os.path.islink(dest) or os.path.exists(dest):
                os.unlink(dest)
            os.symlink(target, dest)
            links += 1
            owner_line(mode, ino.owner, ino.group, rel, target)
            try:
                os.lchown(dest, ino.owner, ino.group)
            except (PermissionError, AttributeError):
                pass
            continue
        elif ino.is_reg:
            data = ino.contents()
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
            with open(dest, "wb") as f:
                f.write(data)
            files += 1
            total += len(data)
            owner_line(mode, ino.owner, ino.group, rel)
        else:
            print("  other (mode %06o): %s" % (mode, rel), file=sys.stderr)
            continue
        os.chmod(dest, stat.S_IMODE(mode))
        try:
            os.chown(dest, ino.owner, ino.group)
        except PermissionError:
            pass

    mpath = os.path.join(outdir, "..", os.path.basename(outdir.rstrip("/")) + ".manifest")
    with open(mpath, "w") as f:
        f.write("\n".join(manifest) + "\n")

    print("extracted %d dirs, %d files (%d bytes), %d links -> %s"
          % (dirs, files, total, links, outdir))
    print("manifest: %s (%d lines)" % (mpath, len(manifest)))
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
