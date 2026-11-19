#!/usr/bin/env python3
"""Fetch a staged file from xnuloader via libusb fastboot 'fetch:NAME'.
Usage: python fb_fetch.py <outpath> [name]   (default name = log.txt)
"""
import os, sys, time
import usb.core, usb.util, usb.backend.libusb1

outpath = sys.argv[1]
name = sys.argv[2] if len(sys.argv) > 2 else "log.txt"
DLL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libusb-1.0.dll")

def get_dev():
    b = usb.backend.libusb1.get_backend(find_library=lambda x: DLL)
    for pid in (0x4EE0, 0xD00D):
        d = usb.core.find(idVendor=0x18D1, idProduct=pid, backend=b)
        if d: return d
    return None

d = get_dev()
if d is None:
    print("NO DEVICE"); sys.exit(2)
d.set_configuration(); cfg = d.get_active_configuration(); intf = cfg[(0,0)]
eo = usb.util.find_descriptor(intf, custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)==usb.util.ENDPOINT_OUT)
ei = usb.util.find_descriptor(intf, custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)==usb.util.ENDPOINT_IN)

def read_reply(timeout=15000):
    r = bytes(ei.read(64, timeout=timeout))
    return r.rstrip(b"\x00")

eo.write(b"upload", timeout=5000)  # xnuloader: 'upload' stages the loader+kernel log (fastboot get_staged)
r = read_reply()
print("reply:", repr(r[:80]))
if not r.startswith(b"DATA"):
    sys.exit(3)
size = int(r[4:].strip(), 16)
print(f"size: {size}")
data = bytearray()
t0 = time.time()
while len(data) < size:
    want = min(4096, size - len(data))
    try:
        chunk = bytes(ei.read(want, timeout=15000))
    except Exception as e:
        print(f"read stopped at {len(data)}/{size}: {e}"); break
    if not chunk: break
    data += chunk
open(outpath, "wb").write(data)
print(f"wrote {len(data)} bytes to {outpath} in {time.time()-t0:.1f}s")
