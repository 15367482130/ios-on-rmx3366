#!/usr/bin/env python3
"""Pre-flight check for the flash toolchain (experience build).

Everything here is bundled with the package, so a failure means the *package* is
incomplete (or the bundled Python is being bypassed), not that the user has to
install anything.  Prints one line per item and returns 0 when it is safe to flash.

Deliberately soft on the USB driver: whether the phone can be opened over libusb is
checked separately (devcheck.py) and the batch script only *offers* to install a
driver -- pressing Enter skips it and the flash still runs.
"""
import os
import sys
import glob
import json
import importlib.metadata as md

HERE = os.path.dirname(os.path.abspath(__file__))

MIN_PY = (3, 8)
MIN_PYUSB = "1.2.0"
MIN_LIBUSB = (1, 0, 20)


def find_parts(path):
    """Sorted .001/.002/... chain that replaces path (release assets cap at 2 GiB)."""
    return sorted(glob.glob(glob.escape(path) + ".[0-9][0-9][0-9]"))


def image_report(path, expected):
    """(ok, message) for one image, whether it is whole or split."""
    if os.path.exists(path):
        size, how = os.path.getsize(path), "whole file"
    else:
        parts = find_parts(path)
        if not parts:
            return False, "%s missing (and no %s.001)" % (os.path.basename(path), os.path.basename(path))
        size = sum(os.path.getsize(p) for p in parts)
        how = "%d parts: %s" % (len(parts), ", ".join(os.path.basename(p) for p in parts))
    msg = "%s (%d MB, %s)" % (os.path.basename(path), size // 1048576, how)
    if expected and size != expected:
        return False, msg + " -- expected %d bytes, got %d (download incomplete?)" % (expected, size)
    return True, msg


def vtuple(s):
    nums = []
    for part in s.strip().split(".")[:3]:
        d = "".join(c for c in part if c.isdigit())
        nums.append(int(d) if d else 0)
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def ok(msg):
    print("  [OK]   " + msg)
    return True


def fail(msg):
    print("  [FAIL] " + msg)
    return False


def get_dll_version(path):
    try:
        import ctypes
        from ctypes import wintypes

        class VS_FIXEDFILEINFO(ctypes.Structure):
            _fields_ = [
                ("dwSignature", wintypes.DWORD),
                ("dwStrucVersion", wintypes.DWORD),
                ("dwFileVersionMS", wintypes.DWORD),
                ("dwFileVersionLS", wintypes.DWORD),
                ("dwProductVersionMS", wintypes.DWORD),
                ("dwProductVersionLS", wintypes.DWORD),
                ("dwFileFlagsMask", wintypes.DWORD),
                ("dwFileFlags", wintypes.DWORD),
                ("dwFileOS", wintypes.DWORD),
                ("dwFileType", wintypes.DWORD),
                ("dwFileSubtype", wintypes.DWORD),
                ("dwFileDateMS", wintypes.DWORD),
                ("dwFileDateLS", wintypes.DWORD),
            ]

        ctypes.windll.version.GetFileVersionInfoW.restype = wintypes.BOOL
        size = ctypes.windll.version.GetFileVersionInfoSizeW(path, None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not ctypes.windll.version.GetFileVersionInfoW(path, None, size, buf):
            return None
        ptr = ctypes.c_void_p()
        length = wintypes.UINT()
        if not ctypes.windll.version.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(length)):
            return None
        ffi = ctypes.cast(ptr, ctypes.POINTER(VS_FIXEDFILEINFO)).contents
        ms, ls = ffi.dwFileVersionMS, ffi.dwFileVersionLS
        return (ms >> 16, ms & 0xFFFF, ls >> 16)
    except Exception:
        return None


def main():
    cfg = {}
    path = os.path.join(HERE, "versions.json")
    if os.path.exists(path):
        try:
            cfg = json.load(open(path, encoding="utf-8"))
        except Exception:
            pass

    print("=== Flash toolchain precheck ===")
    print("  python: %s" % sys.executable)
    print("  folder: %s" % HERE)
    all_ok = True

    if sys.version_info[:2] >= MIN_PY:
        ok("Python %d.%d.%d" % sys.version_info[:3])
    else:
        all_ok &= fail("Python too old: %s" % sys.version.split()[0])

    try:
        ver = md.version("pyusb")
        if vtuple(ver) >= vtuple(MIN_PYUSB):
            ok("pyusb %s" % ver)
        else:
            all_ok &= fail("pyusb too old: %s" % ver)
    except Exception:
        all_ok &= fail("pyusb missing (site-packages)")

    dll = os.path.join(HERE, "libusb-1.0.dll")
    if not os.path.exists(dll):
        all_ok &= fail("libusb-1.0.dll missing")
    else:
        ver = get_dll_version(dll)
        if ver is None:
            ok("libusb-1.0.dll present (%d bytes)" % os.path.getsize(dll))
        elif ver >= MIN_LIBUSB:
            ok("libusb-1.0.dll %d.%d.%d" % ver)
        else:
            all_ok &= fail("libusb-1.0.dll too old: %d.%d.%d" % ver)

    if os.path.exists(os.path.join(HERE, "fb_libusb.py")):
        ok("fb_libusb.py found")
    else:
        all_ok &= fail("fb_libusb.py missing")

    images = cfg.get("images", {})
    sizes = cfg.get("sizes", {})
    for key in ("loader", "system", "payload"):
        name = images.get(key)
        if not name:
            all_ok &= fail("%s not listed in versions.json" % key)
            continue
        good, msg = image_report(os.path.join(HERE, name), sizes.get(name))
        if good:
            ok(msg)
        else:
            all_ok &= fail(msg)

    if all_ok:
        print("=== All checks passed. Safe to flash. ===")
        return 0
    print("=== PRECHECK FAILED: the package is incomplete. Nothing was sent to the phone. ===")
    return 1


if __name__ == "__main__":
    sys.exit(main())
