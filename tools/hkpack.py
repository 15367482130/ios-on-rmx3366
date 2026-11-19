#!/usr/bin/env python3
"""hkpack: an .ipa (or a bare .app) as the phone's hkinstall takes it.

The port's installer (userland/src/hkinstall.m) asks for a ustar archive holding
    Payload/<NAME>.app   the bundle, byte for byte as it is
    ents/<BUNDLE>.plist  each bundle's entitlements, as its own signature lists them
because reading entitlements on the phone would mean a Mach-O parser for no gain.
tools/ipa/pack.sh in the official tree does this on a Mac with codesign; this does it
where we build, with ldid, and refuses an encrypted binary the phone could not run.

usage: hkpack.py INPUT OUTPUT.tar        INPUT: an .ipa or a .app directory
prints: bytes, bundles, sha256
"""
import hashlib
import os
import plistlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

MH_MAGIC_64 = 0xFEEDFACF
LC_ENCRYPTION_INFO = 0x21
LC_ENCRYPTION_INFO_64 = 0x2C


def cryptid(path):
    """The Mach-O's cryptid, or None if it is not Mach-O."""
    with open(path, "rb") as f:
        head = f.read(32)
        if len(head) < 32:
            return None
        magic = int.from_bytes(head[0:4], "little")
        if magic != MH_MAGIC_64:
            return None
        ncmds = int.from_bytes(head[16:20], "little")
        off = 32
        f.seek(0)
        data = f.read()
        for _ in range(ncmds):
            if off + 8 > len(data):
                return None
            cmd, cmdsize = int.from_bytes(data[off:off + 4], "little"), \
                int.from_bytes(data[off + 4:off + 8], "little")
            if cmd in (LC_ENCRYPTION_INFO, LC_ENCRYPTION_INFO_64) and off + 20 <= len(data):
                return int.from_bytes(data[off + 16:off + 20], "little")
            if cmdsize <= 0:
                return None
            off += cmdsize
    return None


def entitlements(binary, ldid):
    """What the signature says the binary is entitled to, as XML bytes, or None."""
    if not os.path.exists(binary):
        return None
    try:
        out = subprocess.run([ldid, "-e", binary], capture_output=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return out if out.strip().startswith(b"<?xml") else None


def main():
    if len(sys.argv) != 3:
        sys.stderr.write("usage: hkpack.py INPUT(.ipa|.app) OUTPUT.tar\n")
        return 2
    src, out = sys.argv[1], sys.argv[2]
    ldid = shutil.which("ldid") or "/root/theos/toolchain/linux/iphone/bin/ldid"
    work = tempfile.mkdtemp(prefix="hkpack.")
    try:
        if os.path.isdir(src):
            os.makedirs(os.path.join(work, "Payload"))
            shutil.copytree(src, os.path.join(work, "Payload", os.path.basename(src)),
                            symlinks=True)
        else:
            with zipfile.ZipFile(src) as z:
                z.extractall(work)
        payload = os.path.join(work, "Payload")
        apps = [d for d in sorted(os.listdir(payload)) if d.endswith(".app")] \
            if os.path.isdir(payload) else []
        if not apps:
            sys.stderr.write("no Payload/*.app in %s\n" % src)
            return 1
        app = os.path.join(payload, apps[0])

        # an encrypted binary is one the phone cannot run: refuse it before it reaches it
        for root, _, files in os.walk(app):
            for name in files:
                path = os.path.join(root, name)
                if os.access(path, os.X_OK) and cryptid(path) == 1:
                    sys.stderr.write("encrypted: %s\n" % os.path.relpath(path, work))
                    return 1

        ents_dir = os.path.join(work, "ents")
        os.makedirs(ents_dir, exist_ok=True)
        bundles = [app] + [os.path.join(app, "PlugIns", e)
                           for e in sorted(os.listdir(os.path.join(app, "PlugIns")))
                           ] if os.path.isdir(os.path.join(app, "PlugIns")) else [app]
        kept = 0
        for bundle in bundles:
            info = os.path.join(bundle, "Info.plist")
            if not os.path.exists(info):
                continue
            with open(info, "rb") as f:
                pl = plistlib.load(f)
            ident = pl.get("CFBundleIdentifier")
            exe = pl.get("CFBundleExecutable")
            if not ident or not exe:
                continue
            xml = entitlements(os.path.join(bundle, exe), ldid)
            if xml:
                with open(os.path.join(ents_dir, ident + ".plist"), "wb") as f:
                    f.write(xml)
                kept += 1

        with tarfile.open(out, "w", format=tarfile.USTAR_FORMAT) as tar:
            for top in ("Payload", "ents"):
                tar.add(os.path.join(work, top), arcname=top)

        with open(out, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        print("%d bytes" % os.path.getsize(out))
        print("%d bundle(s), %d entitlement list(s)" % (len(bundles), kept))
        print(digest)
        print(apps[0])
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
