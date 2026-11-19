#!/usr/bin/env python3
"""Build the GitHub release payload for the experience build.

Why this exists
---------------
GitHub caps a single release asset at 2 GiB and the system image is 2.55 GiB
(2,734,755,840 B), so it cannot be uploaded as one file.  This script splits it
into `system.apfs.001` / `system.apfs.002` and bundles everything else into one
small zip.

The flasher (`fb_libusb.py`) knows how to stream through the `.001` chain, so a
user who downloads the zip plus the two parts gets a working one-click folder:
nothing has to be merged, and the 2.7 GB image never has to exist twice on disk.

Usage
-----
    python tools/make_release.py --src <experience-build-folder> --out release

Output
------
    release/ios-on-rmx3366-exp-v1.zip   scripts, runtime, payload, loader
    release/system.apfs.001 / .002      the system image, split
    release/SHA256SUMS.txt              sha256 of every asset above

The script is idempotent: parts that already cover the source byte-for-byte are
reused instead of rewritten, so re-running it is cheap.
"""
import argparse
import hashlib
import os
import re
import sys
import zipfile

MIB = 1024 * 1024
GITHUB_ASSET_LIMIT = 2 * 1024 * 1024 * 1024          # 2 GiB, hard limit
DEFAULT_PART = 1900 * MIB                            # safely under the limit

SYSTEM_IMAGE = "system.apfs"
SKIP_NAMES = {".token.txt", "desktop.ini", "Thumbs.db", ".DS_Store"}
SKIP_DIRS = {"__pycache__", ".git"}
PART_RE = re.compile(r"^system\.apfs\.(\d{3})$")


def log(msg):
    print(msg, flush=True)


def sha256_of(path, label=None):
    h = hashlib.sha256()
    total = os.path.getsize(path)
    done = 0
    with open(path, "rb") as f:
        while True:
            buf = f.read(8 * MIB)
            if not buf:
                break
            h.update(buf)
            done += len(buf)
            if label and total > 256 * MIB and done % (256 * MIB) < 8 * MIB:
                log("    hashing %s: %d%%" % (label, done * 100 // total))
    return h.hexdigest()


def collect_small_files(src):
    """Every file under src except the system image and its split parts."""
    out = []
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in sorted(files):
            if name == SYSTEM_IMAGE or PART_RE.match(name) or name in SKIP_NAMES:
                continue
            full = os.path.join(root, name)
            rel = os.path.relpath(full, src).replace(os.sep, "/")
            out.append((full, rel))
    return out


def build_zip(src, files, zip_path, prefix):
    tmp = zip_path + ".tmp"
    total = sum(os.path.getsize(p) for p, _ in files)
    log("[1/3] zip %d files (%.1f MB raw) -> %s" % (len(files), total / MIB, os.path.basename(zip_path)))
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for full, rel in files:
            # Badge the batch file so Explorer shows it as a launcher, and keep
            # the timestamps from the build so the archive is reproducible-ish.
            z.write(full, prefix + "/" + rel)
    os.replace(tmp, zip_path)
    log("      %.1f MB on disk" % (os.path.getsize(zip_path) / MIB))
    return zip_path


def existing_parts(out_dir):
    parts = []
    for name in sorted(os.listdir(out_dir)):
        m = PART_RE.match(name)
        if m:
            parts.append((int(m.group(1)), os.path.join(out_dir, name)))
    parts.sort()
    # contiguous from 001
    expect = 1
    for num, _ in parts:
        if num != expect:
            break
        expect += 1
    return [p for _, p in parts[: expect - 1]]


def parts_cover(parts, source_size):
    if not parts:
        return False
    return sum(os.path.getsize(p) for p in parts) == source_size


def split_image(src_path, out_dir, part_size):
    size = os.path.getsize(src_path)
    parts = existing_parts(out_dir)
    if parts_cover(parts, size):
        log("[2/3] split image: reusing existing %d parts (%.1f MB)" % (len(parts), size / MIB))
        return parts
    for p in parts:
        os.remove(p)
    log("[2/3] split image: %.1f MB into %.0f MB parts" % (size / MIB, part_size / MIB))
    parts = []
    idx = 1
    written = 0
    with open(src_path, "rb") as f:
        while True:
            part_path = os.path.join(out_dir, "%s.%03d" % (SYSTEM_IMAGE, idx))
            left = part_size
            got_any = False
            with open(part_path, "wb") as out:
                while left > 0:
                    buf = f.read(min(8 * MIB, left))
                    if not buf:
                        break
                    out.write(buf)
                    left -= len(buf)
                    written += len(buf)
                    got_any = True
            if not got_any:
                os.remove(part_path)
                break
            parts.append(part_path)
            log("      %s  %.1f MB  (%d%%)" % (os.path.basename(part_path),
                                               os.path.getsize(part_path) / MIB,
                                               written * 100 // size))
            idx += 1
            if left > 0:      # source ended before the part filled up
                break
    if written != size:
        raise SystemExit("split failed: wrote %d of %d bytes" % (written, size))
    return parts


def write_sums(out_dir, names):
    log("[3/3] sha256 of %d assets" % len(names))
    lines = []
    for name in names:
        path = os.path.join(out_dir, name)
        digest = sha256_of(path, label=name)
        lines.append("%s  %s" % (digest, name))
        log("      %s  %s" % (digest[:16] + "...", name))
    sums = os.path.join(out_dir, "SHA256SUMS.txt")
    with open(sums, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return sums


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, help="experience build folder (the one with 刷机-体验版.bat)")
    ap.add_argument("--out", default="release", help="output folder (default: release)")
    ap.add_argument("--tag", default="exp-v1", help="used in the zip file name")
    ap.add_argument("--part-size", type=int, default=DEFAULT_PART,
                    help="bytes per split part (default 1900 MiB, must stay under 2 GiB)")
    ap.add_argument("--skip-zip", action="store_true", help="only split + checksum")
    args = ap.parse_args()

    src = os.path.abspath(args.src)
    out = os.path.abspath(args.out)
    if not os.path.isdir(src):
        raise SystemExit("no such folder: %s" % src)
    if args.part_size >= GITHUB_ASSET_LIMIT:
        raise SystemExit("--part-size must be under 2 GiB (GitHub hard limit)")
    os.makedirs(out, exist_ok=True)

    system = os.path.join(src, SYSTEM_IMAGE)
    if not os.path.exists(system):
        raise SystemExit("missing %s in %s" % (SYSTEM_IMAGE, src))

    zip_name = "ios-on-rmx3366-%s.zip" % args.tag
    zip_path = os.path.join(out, zip_name)
    assets = []

    if not args.skip_zip:
        files = collect_small_files(src)
        if not files:
            raise SystemExit("nothing to zip in %s" % src)
        build_zip(src, files, zip_path, "ios-on-rmx3366-%s" % args.tag)
        assets.append(zip_name)
    elif os.path.exists(zip_path):
        assets.append(zip_name)

    parts = split_image(system, out, args.part_size)
    assets += [os.path.basename(p) for p in parts]

    sums = write_sums(out, assets)
    log("")
    log("done. upload these as release assets from %s:" % out)
    for name in assets + [os.path.basename(sums)]:
        log("    %-34s %10.1f MB" % (name, os.path.getsize(os.path.join(out, name)) / MIB))
    log("")
    log("the batch script flashes straight from the parts: no merge step for the user.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
