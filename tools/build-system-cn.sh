#!/bin/bash
set -e
cd /root/work/itn-fpsbuild/userland
source ../xnu-env.sh
IOS=../ios165
CACHE=$IOS/20F66__iPhone10,3_6
SYSTEM=1
	rm -rf sysroot
	cp -al $IOS/rootfs sysroot                      # hard links: no copies of the 0.5 GB
	# launchd must load our choice of jobs, not all 500 that iOS has
	rm -rf sysroot/System/Library/LaunchDaemons sysroot/System/Library/NanoLaunchDaemons \
		sysroot/System/Library/LaunchAngels sysroot/System/Library/xpc/launchd.plist
	ln -s /redwood/LaunchDaemons sysroot/System/Library/LaunchDaemons
	mkdir -p sysroot/redwood sysroot/sbin
	# where the kernel mounts the iOS root container off the phone's flash (boot-arg apfs_volume=):
	# iOS has no /System/Volumes, and nothing can make a directory in this image once it is built
	mkdir -p sysroot/System/Volumes/iOS
	# the applications iOS installs on its first boot are system applications here (see select-system.py)
	if [ -d sysroot/private/var/staged_system_apps ]; then
		mv sysroot/private/var/staged_system_apps/* sysroot/Applications/
		rm -rf sysroot/private/var
	fi
	mv sysroot/sbin/launchd sysroot/sbin/launchd.ios
	cp obj/stage0 sysroot/sbin/launchd
	cp -a sysroot/sbin/launchd.ios sysroot/sbin/launchd.darwin
	# the full PingFang collection (36 faces): the trimmed copy keeps only Regular and Semibold, so
	# anything drawn at another weight (home-screen icon labels, Safari chrome: Medium) came out as tofu
	rm -f sysroot/System/Library/Fonts/LanguageSupport/PingFang.ttc
	cp /root/work/fonts/PingFang-full.ttc sysroot/System/Library/Fonts/LanguageSupport/PingFang.ttc

	# the audio DSP's firmware, the phone's own from ../fw-audio (never in the repository), where the kernel reads
	# it once the root is mounted (bsd/dev/hk_adsp.c, adsp=1): 20 MB that do not fit beside GL=1 in the small image
	if [ -f ../fw-audio/adsp.mdt ]; then
		mkdir -p sysroot/fw
		cp ../fw-audio/adsp.mdt ../fw-audio/adsp.b0[2-9] ../fw-audio/adsp.b[1-9][0-9] sysroot/fw/
	fi
	# ... and the speaker amplifiers' configuration, the phone's /vendor/etc/aw882xx_acf.bin (bsd/dev/hk_speaker.c,
	# for sound=3), the OnePlus 8's /vendor/firmware/tfa98xx.cnt (bsd/dev/instantnoodle_speaker.c): Android's own
	# register values, which are not in the repository either
	for amps in aw882xx_acf.bin tfa98xx.cnt; do
		if [ -f ../fw-audio/$amps ]; then
			mkdir -p sysroot/fw
			cp ../fw-audio/$amps sysroot/fw/
		fi
	done
	# the package manager's prefix, when tools/mk-jb.sh has fetched one: the Procursus bootstrap with
	# Sileo in it, as /jb. It cannot live at /var/jb in the image -- /private/var is a memory
	# filesystem made afresh at every boot -- so init copies it there (src/init.c, copy_tree).
	if [ -d ../jb/root/var/jb ]; then
		rm -rf sysroot/jb
		cp -a ../jb/root/var/jb sysroot/jb
		# the applications of the prefix are system applications here: LaunchServices builds its
		# database afresh at every boot by walking /Applications, which is how their icons appear
		for app in sysroot/jb/Applications/*.app; do
			[ -d "$app" ] && cp -a "$app" sysroot/Applications/
		done
		# Sileo moves, copies and removes files as root with /bin/mv, /bin/cp, /bin/rm, /bin/mkdir and
		# /bin/chmod -- where a jailbreak with a writable root keeps them -- and iOS's /bin has df and ps
		# alone: every one of those spawns failed with nothing said, and the package it had downloaded never
		# reached apt's archives ("Unable to fetch some archives"). The prefix's own programs, by those names.
		for c in $SILEO_BIN; do
			ln -sf /var/jb/usr/bin/$c sysroot/bin/$c
		done
		echo "  the package manager's prefix: $(du -sh sysroot/jb | cut -f1) as /jb (init puts it at /var/jb)"
	fi
	# An application of this port's own, registered the same free way the prefix's are: a plain
	# directory in /Applications, which the LaunchServices database is rebuilt from at every boot
	# by walking that directory -- no installd, no container, no uicache. cp -a and not a link,
	# because a bundle of symbolic links is refused ("Unable to register") and the boot-time
	# registrar passes over mount points.
	#
	# This is in the SYSTEM image and not the small one, so a change to it costs a 2.5 GB rebuild
	# and a re-upload: SYSTEM=1 is what makes this line run again.
	if [ -d obj/HKTriangle.app ]; then
		cp -a obj/HKTriangle.app sysroot/Applications/
		echo "  HKTriangle.app in /Applications (com.hackios.triangle, scheme hktriangle:)"
	fi
	# Applications from outside this tree: every .app in ../apps, which is kept out of the
	# repository the way ../fw-* and ../jb are, so that nothing of somebody else's package can
	# reach it. They go into /Applications beside the port's own on exactly the same terms --
	# a plain directory, which LaunchServices finds by walking that folder at every boot.
	#
	# cp -aL and not cp -a: a bundle made of symbolic links is refused ("Unable to register"),
	# so whatever a link points at is copied as the file itself.
	for app in ../apps/*.app; do
		[ -d "$app" ] || continue
		cp -aL "$app" sysroot/Applications/
		echo "  ${app##*/} in /Applications ($(du -sm "$app" | cut -f1) MB from ../apps)"
	done
	# Our physical audio device; opt-in Bluetooth uses Apple's unmodified audio plug-in alongside it.
	mkdir -p sysroot/System/Library/Audio/Plug-Ins/HAL
	ln -s /redwood/lib/HKAudio.driver sysroot/System/Library/Audio/Plug-Ins/HAL/HKAudio.driver
	if [ "$BLUETOOTH" = 1 ]; then
		cp -a "$bt_hal" sysroot/System/Library/Audio/Plug-Ins/HAL/
	else
		rm -rf sysroot/System/Library/Audio/Plug-Ins/HAL/BTAudioHALPlugin.driver
	fi
	# ... and our Metal plug-in, at the one path Metal's own discovery can open: step 3 composes
	# "/System/Library/Extensions/" + MetalPluginName + ".bundle" and opens it with NSBundle
	# (docs/metal.md 1). Same shape as the audio plug-in above -- a link into /redwood/lib, where
	# the bundle itself travels in the small image -- because this directory is iOS's own and
	# nothing can be added to it after the image is built.
	#
	# This link is inert on a boot that does not ask for Metal: nothing composes that path until
	# MetalPluginName is on the IOAcceleratorES service, and only boot-arg metal=1 lets a process
	# put it there (iokit/Kernel/MiniIOMobileFramebuffer.cpp). So it is not behind a switch of its
	# own -- a switch here would cost a 2.5 GB system.apfs rebuild and a re-upload every time it
	# was flipped, and buy nothing a missing boot-arg does not already buy.
	mkdir -p sysroot/System/Library/Extensions
	ln -s /redwood/lib/HKMetal.bundle sysroot/System/Library/Extensions/HKMetal.bundle
	# the boot logo backboardd shows, bootlogo/ (mkbootlogo.py) in place of Apple's; rm first: hard links into ios165
	if ls bootlogo/apple-logo*.png >/dev/null 2>&1; then
		rm -f sysroot/System/Library/PrivateFrameworks/ProgressUI.framework/apple-logo*.png
		cp bootlogo/apple-logo*.png sysroot/System/Library/PrivateFrameworks/ProgressUI.framework/
	fi
	# the OS cryptex: on a device a separate volume grafted at /System/Cryptexes/OS. It holds the dyld
	# shared cache (dyld looks there first) and a few libraries and resources outside the cache.
	mkdir -p sysroot/System/Cryptexes
	if [ -d $IOS/cryptex ]; then cp -al $IOS/cryptex sysroot/System/Cryptexes/OS; fi
	# the App cryptex, the same way: Safari's daemons (eight launchd jobs run them from there), its settings and
	# the bundles around it, which the root's links reach (System/Library/PreferenceBundles/MobileSafariSettings.bundle...)
	if [ -d $IOS/cryptex-app ]; then cp -al $IOS/cryptex-app sysroot/System/Cryptexes/App; fi
	D=sysroot/System/Cryptexes/OS/System/Library/Caches/com.apple.dyld
	mkdir -p $D
	for f in $CACHE/dyld_shared_cache_arm64*; do
		case "$f" in *.symbols) continue ;; esac     # symbolication data, never mapped
		# -f: a cryptex fetched with the cache already in it would otherwise stop the build
		ln -f "$f" $D/
	done
	# zlib where it saves room, as Apple keeps the root (a small file whole in its attribute): 5.4 GB of
	# files in 2.5 GB, what fits into the phone's RAM beside iOS
	# the three things the image the phone has been running was also made with
	mkdir -p sysroot/System/Volumes/Darwin
	mkdir -p sysroot/System/Library/Audio/Plug-Ins/HAL
	ln -sfn /redwood/lib/HakiosAudio.driver sysroot/System/Library/Audio/Plug-Ins/HAL/HakiosAudio.driver
	python3 mkhighrate.py sysroot
	python3 ../tools/apfs/mkapfs.py -z -o system.apfs System=sysroot,manifest=$IOS/system.manifest | tail -1
	[ -z "$CHECK" ] || ../tools/apfs/check-image.sh system.apfs System=sysroot,manifest=$IOS/system.manifest
	rm -rf sysroot
