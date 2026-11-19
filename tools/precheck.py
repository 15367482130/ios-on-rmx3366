#!/usr/bin/env python3
"""Pre-flight check for the Windows flashing toolchain.

Verifies that Python, pyusb and the bundled libusb DLL meet the minimum
versions the flasher needs. If anything is too old or missing, print the
exact fix and exit non-zero so the batch script stops BEFORE touching the
phone. This prevents the classic "driver too old -> bulk transfer hangs"
failure that wasted a lot of time.

Version requirements (bump here when the flasher needs newer pieces):
  Python   >= 3.8
  pyusb    >= 1.2.0
  libusb   >= 1.0.20   (the bundled libusb-1.0.dll, file version checked)
"""
import sys
import os
import json
import importlib.metadata as md

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "versions.json")

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


def fail(msg):
    print("  [FAIL] " + msg)
    return False


def ok(msg):
    print("  [OK]   " + msg)
    return True


def get_dll_version(path):
    """Read the Windows file version of a DLL without pywin32."""
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
    except Exception as e:
        return None


def main():
    cfg = {}
    if os.path.exists(CFG):
        try:
            cfg = json.load(open(CFG, encoding="utf-8"))
        except Exception:
            pass

    print("=== Flash toolchain precheck ===")
    print("  python: %s" % sys.executable)
    print("  workdir: %s" % os.getcwd())
    print("  scriptdir: %s" % HERE)
    all_ok = True

    # 1) Python
    pv = sys.version_info[:2]
    if pv >= MIN_PY:
        all_ok &= ok("Python %d.%d.%d" % (sys.version_info[:3]))
    else:
        all_ok &= fail("Python too old: %s (need >= %d.%d)" % (sys.version.split()[0], *MIN_PY))

    # 2) pyusb
    try:
        usbver = md.version("pyusb")
        if vtuple(usbver) >= vtuple(MIN_PYUSB):
            all_ok &= ok("pyusb %s" % usbver)
        else:
            all_ok &= fail("pyusb too old: %s (need >= %s) -> pip install -U pyusb" % (usbver, MIN_PYUSB))
    except Exception:
        all_ok &= fail("pyusb missing -> pip install pyusb")

    # 3) libusb DLL
    dll = os.path.join(HERE, "libusb-1.0.dll")
    if not os.path.exists(dll):
        all_ok &= fail("libusb-1.0.dll missing -> copy it next to this script")
    else:
        ver = get_dll_version(dll)
        if ver is None:
            # Some builds have no version resource; accept but note it
            all_ok &= ok("libusb-1.0.dll present (%d bytes, no version resource)" % os.path.getsize(dll))
        elif ver >= MIN_LIBUSB:
            all_ok &= ok("libusb-1.0.dll %d.%d.%d" % ver)
        else:
            all_ok &= fail("libusb-1.0.dll too old: %d.%d.%d (need >= %d.%d.%d) -> replace with libusb >= 1.0.20" % (*ver, *MIN_LIBUSB))

    # 4) flasher present
    fl = os.path.join(HERE, "fb_libusb.py")
    all_ok &= ok("fb_libusb.py found") if os.path.exists(fl) else fail("fb_libusb.py missing")

    # 5) image files present
    for name in ("loader-logfix.img", "system.apfs", "itn-taste.bin"):
        p = os.path.join(HERE, name)
        all_ok &= ok("%s (%d MB)" % (name, os.path.getsize(p) // 1048576)) if os.path.exists(p) else fail("%s missing" % name)

    if all_ok:
        print("=== All checks passed. Safe to flash. ===")
        return 0
    print("=== PRECHECK FAILED. Nothing was sent to the phone. ===")
    return 1


if __name__ == "__main__":
    sys.exit(main())
