#!/usr/bin/env python3
"""Minimal fastboot client over libusb, bypassing fastboot.exe entirely.

Reason: on this Windows box the stock-ABL device (VID_18D1 PID_D00D) is bound
to a 2012 libwdi WinUSB driver; fastboot.exe's bulk transfers hang, but raw
libusb bulk transfers work (probe_libusb.py got OKAY from getvar:product).
This implements the fastboot protocol directly so the whole flash can be done
from Windows without WSL and without touching drivers.

Commands used by xnuloader:
  getvar:NAME            -> OKAY<value> / FAIL<msg>
  oem ramdisk            -> OKAY
  download:HEXLEN        -> DATAHEXLEN, then stream exactly HEXLEN bytes, -> OKAY
  boot                   -> OKAY (boots the last downloaded payload as kernel)
  oem run                -> OKAY (starts the staged payload)

xnuloader stage flow (from loader.c):
  fastboot boot <loader.img>   = download(loader) + "boot"
  oem ramdisk                  = switch download target to ramdisk window
  stage <system.apfs>          = download(system)   [lands in ramdisk window]
  stage <payload.bin>          = download(payload)  [lands in ramdisk window]
  oem run                      = start

Usage:
  python fb_libusb.py devices
  python fb_libusb.py getvar product
  python fb_libusb.py flash <loader.img> <system.apfs> <payload.bin>
"""
import sys, os, time, struct

import usb.core
import usb.util
import usb.backend.libusb1

VID = 0x18D1
# D00D = stock ABL fastboot; 4EE0 = xnuloader (after `boot loader`)
PIDS = [0xD00D, 0x4EE0]
DLL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libusb-1.0.dll")


# ONE shared backend for the whole process. Creating a second libusb context
# mid-flash makes libusb_open fail with "Access denied" on Windows.
_BACKEND = usb.backend.libusb1.get_backend(find_library=lambda x: DLL)


def get_dev(pid=None):
    if _BACKEND is None:
        raise RuntimeError("libusb backend unavailable")
    if pid is not None:
        return usb.core.find(idVendor=VID, idProduct=pid, backend=_BACKEND)
    for p in PIDS:
        d = usb.core.find(idVendor=VID, idProduct=p, backend=_BACKEND)
        if d:
            return d
    return None


def open_fastboot(pid=None, tries=15, delay=2.0):
    """A Fastboot handle, waiting out the window in which a just-re-enumerated
    device is visible but not openable yet.

    Right after `boot loader` the device comes back as 4EE0 and Windows has not
    finished binding the driver to it: libusb_open then fails with
    LIBUSB_ERROR_NOT_SUPPORTED (pyusb reports "Operation not supported"). It is
    a race, not a fault -- a few seconds later the same open succeeds, which is
    why a second run of the script used to be enough.
    """
    last = None
    for attempt in range(1, tries + 1):
        dev = get_dev(pid)
        if dev is not None:
            try:
                return Fastboot(dev)
            except (NotImplementedError, usb.core.USBError) as error:
                last = error
                try:
                    usb.util.dispose_resources(dev)
                except Exception:
                    pass
                print(f"    open attempt {attempt}: {type(error).__name__}, waiting for the driver", flush=True)
        if attempt < tries:
            time.sleep(delay)
    if last is not None:
        raise last
    raise RuntimeError("no fastboot device")


class Fastboot:
    def __init__(self, dev):
        self.dev = dev
        dev.set_configuration()
        cfg = dev.get_active_configuration()
        intf = cfg[(0, 0)]
        self.ep_out = usb.util.find_descriptor(intf, custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT)
        self.ep_in = usb.util.find_descriptor(intf, custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN)
        assert self.ep_out and self.ep_in

    def reopen(self):
        """Drop the handle and take the device again, same PID.

        A handle that outlived a re-enumeration (or a transfer the device gave
        up on) answers every command with a timeout; closing it and finding the
        device afresh is the cheapest thing that can still work from this side.
        """
        pid = self.dev.idProduct
        try:
            usb.util.dispose_resources(self.dev)
        except Exception:
            pass
        fresh = open_fastboot(pid, tries=5, delay=1.5)
        self.dev, self.ep_out, self.ep_in = fresh.dev, fresh.ep_out, fresh.ep_in
        return self

    def _read_reply(self, timeout=10000):
        # fastboot replies are text packets on bulk IN; some replies are NUL-padded
        data = self.ep_in.read(64, timeout=timeout)
        s = bytes(data).decode("ascii", "replace")
        # keep DATAxxxx / OKAY / FAIL + payload but drop NUL padding
        return s.rstrip("\x00")

    def read_stream(self, command, out_path, timeout=60000):
        """Send COMMAND, read its DATAxxxx header, then drain exactly that many bytes.

        Never stop early.  A staging the host walks away from leaves the device's reply queued:
        the next command then reads the tail of this one, and every answer after it is the one
        before -- a device that enumerates and ignores everything until the cable is pulled,
        because pulling the cable is what cancels the transfer.  If the read fails, raise: a
        half-read stream must not be followed by another command.
        """
        self.ep_out.write(command, timeout=10000)
        head = self._read_reply(timeout=timeout)
        if not head.startswith("DATA"):
            raise RuntimeError(f"{command!r} -> {head!r}")
        total = int(head[4:].strip(), 16)
        got = 0
        with open(out_path, "wb") as out:
            while got < total:
                piece = self.ep_in.read(min(65536, total - got), timeout=timeout)
                if not piece:
                    raise RuntimeError(f"stalled at {got} of {total} bytes")
                out.write(bytes(piece))
                got += len(piece)
        print(f"    {got} bytes -> {out_path}", flush=True)
        return got

    def cmd(self, cmd, timeout=10000):
        self.ep_out.write(cmd.encode("ascii"), timeout=timeout)
        r = self._read_reply(timeout)
        return r

    def download(self, data, chunk_report=True):
        total = len(data)
        t0 = time.time()
        # Retry the whole download handshake a few times: if a previous run left
        # the device mid-download, a fresh download: command usually resets it.
        last = None
        for attempt in range(1, 4):
            try:
                # CRITICAL: loader.c parse_number() only accepts LOWERCASE a-f.
                # Uppercase hex makes it stop early -> wrong DATA size -> hang.
                r = self.cmd(f"download:{total:x}", timeout=10000)
                if not r.startswith("DATA"):
                    last = RuntimeError(f"download: expected DATA..., got {r!r}")
                    print(f"    attempt {attempt}: {last}", flush=True)
                    time.sleep(2)
                    continue
                want = int(r[4:].strip().rstrip("\x00").strip(), 16)
                if want != total:
                    raise RuntimeError(f"download: device wants {want}, we have {total}")
                off = 0
                while off < total:
                    n = min(65536, total - off)
                    self.ep_out.write(data[off:off+n], timeout=30000)
                    off += n
                    if chunk_report and (off // (32*1024*1024)) != ((off-n) // (32*1024*1024)):
                        print(f"    sent {off}/{total} ({off*100//total}%)", flush=True)
                r = self._read_reply(timeout=120000)
                if not r.startswith("OKAY"):
                    raise RuntimeError(f"download: after data got {r!r}")
                dt = time.time() - t0
                if chunk_report:
                    print(f"    {total} bytes in {dt:.1f}s ({total/dt/1e6:.1f} MB/s)", flush=True)
                return dt
            except usb.core.USBTimeoutError as e:
                last = e
                print(f"    attempt {attempt}: timeout, retrying handshake", flush=True)
                time.sleep(2)
                try:
                    self.reopen()
                except Exception as error:
                    print(f"    reopen: {type(error).__name__}: {error}", flush=True)
        hint = ("device still enumerates but does not answer: its fastboot endpoint is stuck. "
                "Close/reopen cannot clear that from this side (clear_halt, set_configuration and a "
                "libusb port reset were all tried); a loader built with the abort_xfer fix, or a "
                "cable replug, is what clears it.")
        raise RuntimeError(f"{last} -- {hint}") from last


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    try:
        fb = open_fastboot()
    except (RuntimeError, NotImplementedError, usb.core.USBError) as error:
        print(f"NO DEVICE ({type(error).__name__}: {error})")
        return 2
    dev = fb.dev
    serial = usb.util.get_string(dev, dev.iSerialNumber)
    print(f"device: {serial} (bus {dev.bus} addr {dev.address})")

    op = args[0]
    if op == "devices":
        print(f"{serial}\tfastboot")
        return 0
    if op == "getvar":
        r = fb.cmd(f"getvar:{args[1]}")
        print(r)
        return 0 if r.startswith("OKAY") else 1
    if op == "oem":
        r = fb.cmd("oem " + " ".join(args[1:]))
        print(r)
        return 0 if r.startswith("OKAY") else 1
    if op == "reboot":
        # The ABL accepts one `boot` per cold start: once a boot image has been refused, every
        # later `boot` answers "Failed to load/authenticate boot image" until the phone is
        # powered off and on.  A soft reboot into the bootloader clears that, and it needs no
        # hand on the phone -- so always do this before the next attempt.
        target = args[1] if len(args) > 1 else "bootloader"
        r = fb.cmd(f"reboot-{target}" if target != "bootloader" else "reboot-bootloader", timeout=20000)
        print(r)
        return 0 if r.startswith("OKAY") else 1
    if op == "log":
        # stage the log and drain it in the same run: the only safe way to read one, because a
        # staging left half-read is exactly what wedges the endpoint (see read_stream).
        out = args[1] if len(args) > 1 else "_log.txt"
        r = fb.cmd("oem log", timeout=60000)
        print("   ", r)
        fb.read_stream("upload", out)
        return 0
    if op == "run":
        # Re-run iOS with a new payload only: the system volume is already in the loader's
        # ramdisk window (download_to_ramdisk is cleared by the flash that put it there), so a
        # download now lands in the payload area and `oem run` starts the kernel from it.
        payload = args[1]
        r = fb.cmd("oem stop", timeout=15000)
        print("oem stop:", r)
        time.sleep(6)
        print(f"download payload {os.path.basename(payload)} ({os.path.getsize(payload)} bytes)")
        fb.download(open(payload, "rb").read())
        r = fb.cmd("oem run", timeout=30000)
        print("oem run:", r)
        return 0 if r.startswith("OKAY") else 1
    if op == "flash":
        loader, system, payload = args[1], args[2], args[3]
        force_boot = "--force-boot" in args
        args = [a for a in args if a != "--force-boot"]
        loader, system, payload = args[1], args[2], args[3]
        t0 = time.time()
        # If the loader is already running (PID 4EE0), skip the boot stage,
        # UNLESS --force-boot is given (e.g. to load a rebuilt loader with a
        # higher PAYLOAD_MAX_SIZE). Reuse the already-open dev/fb from main().
        if dev.idProduct == 0x4EE0 and not force_boot:
            print(f"[1/5] loader already running (bus {dev.bus} addr {dev.address}), skip boot")
        else:
            print(f"[1/5] download loader {os.path.basename(loader)} ({os.path.getsize(loader)} bytes)")
            fb.download(open(loader, "rb").read())
            print("[2/5] boot loader")
            r = fb.cmd("boot", timeout=30000)
            print("   ", r)
            if not r.startswith("OKAY"):
                return 3
            # loader re-enumerates as 4EE0 with a NEW usb address
            print("    waiting for xnuloader (4EE0) to re-enumerate...")
            fb = None
            try:
                fb = open_fastboot(0x4EE0, tries=20, delay=3.0)
            except (RuntimeError, NotImplementedError, usb.core.USBError):
                print("    xnuloader did not re-enumerate")
                return 4
            dev = fb.dev
            print(f"    loader up: bus {dev.bus} addr {dev.address}")
        # 3) oem ramdisk
        print("[3/5] oem ramdisk")
        r = fb.cmd("oem ramdisk")
        print("   ", r)
        if not r.startswith("OKAY"):
            return 5
        # 4) download system.apfs + payload (into ramdisk window)
        print(f"[4/5] download system.apfs ({os.path.getsize(system)} bytes)")
        fb.download(open(system, "rb").read())
        print(f"[4/5] download payload {os.path.basename(payload)} ({os.path.getsize(payload)} bytes)")
        fb.download(open(payload, "rb").read())
        # 5) oem run
        print("[5/5] oem run")
        r = fb.cmd("oem run", timeout=30000)
        print("   ", r)
        print(f"FLASH DONE, total {time.time()-t0:.1f}s")
        return 0
    print(f"unknown op: {op}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
