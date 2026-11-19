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
import json
import importlib.metadata as md

HERE = os.path.dirname(os.path.abspath(__file__))

MIN_PY = (3, 8)
MIN_PYUSB = "1.2.0"
MIN_LIBUSB = (1, 0, 20)


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
    for key in ("loader", "system", "payload"):
        name = images.get(key)
        p = os.path.join(HERE, name) if name else None
        if p and os.path.exists(p):
            ok("%s (%d MB)" % (name, os.path.getsize(p) // 1048576))
        else:
            all_ok &= fail("%s missing" % (name or key))

    if all_ok:
        print("=== All checks passed. Safe to flash. ===")
        return 0
    print("=== PRECHECK FAILED: the package is incomplete. Nothing was sent to the phone. ===")
    return 1


if __name__ == "__main__":
    sys.exit(main())
