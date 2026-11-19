#!/usr/bin/env python3
"""Is the phone reachable for flashing, and is it a driver problem or a mode problem?

Exit codes:
  0  libusb can open a Google/Android fastboot device -- nothing to do
  1  Windows sees the phone, but libusb cannot open it  -> the USB driver is wrong
  2  no Google/Android USB device at all                -> the phone is not in fastboot
"""
import sys
import subprocess

VID = 0x18D1


def libusb_devices():
    try:
        import usb.core
    except Exception as error:
        print("  pyusb could not be imported: %s" % error)
        return []
    try:
        return [d for d in usb.core.find(find_all=True, idVendor=VID)]
    except Exception:
        return []


def pnp_devices():
    """Windows' own view: instance ids of present USB devices with Google's vendor id."""
    script = (
        "Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | "
        "Where-Object { $_.InstanceId -like 'USB\\VID_18D1*' } | "
        "ForEach-Object { $_.Status + ' ' + $_.InstanceId }"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=40,
        ).stdout
    except Exception:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def main():
    found = libusb_devices()
    if found:
        for d in found:
            print("  [OK]   libusb: %04x:%04x on bus %s" % (d.idVendor, d.idProduct, d.bus))
        return 0

    seen = pnp_devices()
    if seen:
        print("  Windows sees the phone but libusb cannot open it:")
        for line in seen:
            print("      " + line)
        # 4EE0 is xnuloader: the phone is already past fastboot -- that is not a driver issue,
        # and flashing from here would need a different entry point entirely.
        if any("PID_4EE0" in line.upper() for line in seen):
            print("  That is xnuloader (4EE0): iOS/loader is already running.")
            print("  Power the phone off, then hold volume-down + power for fastboot.")
            return 2
        print("  This is the USB driver, not the phone.")
        return 1

    print("  No device with Google's vendor id (18d1) is present.")
    print("  The phone must be in fastboot before flashing:")
    print("    power off, then hold volume-down + power until the fastboot screen appears.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
