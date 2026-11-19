#!/bin/bash
# hkadd_app.sh TAR [PAYLOAD]  -- put one app into the next payload.
#
# The port installs an app the free way (docs/research/ipa-install.md): hkinstall in the
# ramdisk fetches a ustar (hkpack.py: Payload/<NAME>.app + ents/) from this PC over Wi-Fi,
# asks containermanagerd for its containers and registers it with LaunchServices. There is
# no installd in it and no Apple signature is checked on that path; the kernel runs with
# cs_enforcement_disable=1.
#
# So the app's own fetch line lives in /redwood/etc/rc.jobs, and changing it means one
# small ramdisk (26 MB) and one payload (44 MB): the 2.7 GB system image is untouched.
#
# usage: hkadd_app.sh TAR [PAYLOAD]
#   TAR      what hkpack.py made
#   PAYLOAD  default: outputs/kona-kernel/itn-cn-inst.bin, repacked from itn-cn.bin
# env: HK_PC_IP (default 192.168.2.100), HK_PORT (18770), HK_BUNDLE (read from the .app's
#      Info.plist), HK_BASE_PAYLOAD (default itn-cn.bin)
set -e

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
TAR=${1:?usage: hkadd_app.sh TAR [PAYLOAD]}
OUT=${2:-$HERE/itn-cn-inst.bin}
PC_IP=${HK_PC_IP:-192.168.2.100}
PORT=${HK_PORT:-18770}
BASE=${HK_BASE_PAYLOAD:-itn-cn.bin}
RD=/root/work/itn-fpsbuild

[ -f "$TAR" ] || { echo "no $TAR"; exit 1; }
TAR=$(cd "$(dirname "$TAR")" && pwd)/$(basename "$TAR")
NAME=$(basename "$TAR")
SHA=$(sha256sum "$TAR" | cut -d' ' -f1)

# the bundle id, from the archive itself: the .app's Info.plist
BUNDLE=${HK_BUNDLE:-}
if [ -z "$BUNDLE" ]; then
	W=$(mktemp -d)
	tar xf "$TAR" -C "$W" Payload 2>/dev/null
	BUNDLE=$(python3 - "$W" <<'PY'
import glob, plistlib, sys
for p in glob.glob(sys.argv[1] + "/Payload/*.app/Info.plist"):
    print(plistlib.load(open(p, "rb")).get("CFBundleIdentifier", ""))
    break
PY
)
	rm -rf "$W"
fi
[ -n "$BUNDLE" ] || { echo "cannot read CFBundleIdentifier from $TAR"; exit 1; }

echo "app     $NAME"
echo "bundle  $BUNDLE"
echo "sha256  $SHA"
echo "served  http://$PC_IP:$PORT/$NAME"

# the ramdisk's job list: the one line that does the install, and nothing else at boot
cat > "$RD/rd-full/etc/rc.jobs" <<EOF
# Commands run by the launchd job com.hakios.demo (see com.hakios.demo.plist).
#
# The .ipa as hkpack.py made it (ustar: Payload/<NAME>.app + ents/) is fetched from the PC
# over Wi-Fi and installed by hkinstall, which registers it with LaunchServices and asks
# containermanagerd for its containers: no installd, and no Apple signature is checked
# there. The icon appears on the home screen; a finger starts it (a program's own request
# to open is refused by FrontBoard, docs/research/ipa-install.md).
/redwood/bin/hkinstall alarm 300 wait-net 120 fetch $PC_IP $PORT /$NAME $SHA /var/tmp/$NAME unpack /var/tmp/$NAME /var/tmp/hk-unpack install /var/tmp/hk-unpack state $BUNDLE
EOF

cd "$RD"
python3 /root/work/instantnoodle-xnu/tools/apfs/mkapfs.py -z --plain fw \
	-o rd-inst.apfs 'hackios=rd-full,manifest=rd-full.manifest' 2>&1 | tail -2
cp rd-inst.apfs "$HERE/rd-inst.apfs"

cd "$HERE"
python3 make_payload.py -o "$(basename "$OUT")" --from "$BASE" --ramdisk rd-inst.apfs | tail -3
ls -la "$(basename "$OUT")"
echo
echo "now: python hkserve.py $NAME $PC_IP $PORT 1800    (on this PC, while the phone boots)"
