"""Write the ramdisk's rc.jobs: the install line, retried while the phone is joined to Wi-Fi.

Why repeated: /private/var is RAM (hk_data=2), so the Wi-Fi password that wifid keeps in
the keychain is gone at every boot; the network is joined by hand in Settings each time.
The job list therefore waits and asks again, so that the install happens by itself once
the phone is on the network, without another flash.

init's job runner (userland/src/init.c, run_rc) reads one line per command, runs them in
order waiting for each, has a built-in "sleep SECONDS" that starts no program, and goes on
to the next line when one fails.
"""
import hashlib
import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))
TAR = os.path.join(HERE, "hktest.tar")
OUT = "/root/work/itn-fpsbuild/rd-full/etc/rc.jobs"

PC_IP = "192.168.2.100"
PORT = 18770
NAME = os.path.basename(TAR)
BUNDLE = "com.hackios.hktest"

sha = hashlib.sha256(open(TAR, "rb").read()).hexdigest()

# "claim system" is what hkinstall's own .ipa path sets unconditionally
# (install_ipa: claim_signer = system_registration = true).  Without them the LaunchServices
# description carries no SignerIdentity / SignerOrganization / SignatureVersion and the app is
# registered as a plain user bundle, which FrontBoard refuses to start.
install = ("/redwood/bin/hkinstall alarm 120 wait-net 45 claim system fetch {ip} {port} /{name} {sha} "
           "/var/tmp/{name} unpack /var/tmp/{name} /var/tmp/hk-unpack install "
           "/var/tmp/hk-unpack state {bundle}").format(
    ip=PC_IP, port=PORT, name=NAME, sha=sha, bundle=BUNDLE)

# what the system thinks its language is, and what /private/var actually got: one HTTP POST to
# this PC, once, right after the first install attempt.  The answer to "it is still English" is
# in one of those lines, and a phone with no terminal has no other way to say it.
diag = "/redwood/bin/hkinstall alarm 90 wait-net 45 diagnose {ip} {port} /diag".format(ip=PC_IP, port=PORT)

lines = [
    "# Commands run by the launchd job com.hakios.demo (see com.hakios.demo.plist).",
    "#",
    "# hkinstall fetches hkpack.py's ustar from this PC over Wi-Fi, asks containermanagerd",
    "# for the bundle's containers and registers it with LaunchServices: no installd, and no",
    "# Apple signature is read on that path (docs/research/ipa-install.md).",
    "#",
    "# /private/var is RAM here (hk_data=2), so the Wi-Fi password is not kept from one boot",
    "# to the next and the network is joined by hand in Settings: the attempt is repeated",
    "# once a minute for about forty minutes, so there is no hurry to reach Settings -- the",
    "# install starts by itself at the first attempt that finds the network up. A line that",
    "# fails does not stop the list.",
    "sleep 30",
]
for _ in range(40):
    # the report goes first in every round: it needs only the network, so it arrives even
    # when this round's install has nothing to do yet
    lines.append(diag)
    lines.append(install)
    lines.append("sleep 60")

with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
    f.write("\n".join(lines) + "\n")

print("wrote", OUT)
print("sha256", sha)
print("attempts", 40, "ip", PC_IP, "port", PORT)
