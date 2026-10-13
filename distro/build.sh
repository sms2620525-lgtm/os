#!/bin/sh
# Build the Fenestra OS live/installable ISO.
#   sudo ./build.sh          # amd64 ISO for PCs
#   sudo ./build.sh arm64    # arm64 ISO for Apple Silicon Macs (UTM/Parallels/VMware) and ARM PCs
# Requirements: Debian/Ubuntu host with live-build (sudo apt install live-build), root, ~15 GB disk.
# Build the arm64 image on an arm64 machine (or install qemu-user-static + binfmt-support for cross builds).
set -e
export FENESTRA_ARCH="${1:-${FENESTRA_ARCH:-amd64}}"
cd "$(dirname "$0")"
[ "$(id -u)" -eq 0 ] || { echo "run as root (sudo ./build.sh)"; exit 1; }
command -v lb >/dev/null || { echo "install live-build first: apt install live-build"; exit 1; }

# Copy the Fenestra sources into the image; the 0500 hook installs and removes them.
rm -rf config/includes.chroot/opt/fenestra-src
mkdir -p config/includes.chroot/opt/fenestra-src
(cd .. && tar --exclude=./distro --exclude=./.git -cf - .) | tar -xf - -C config/includes.chroot/opt/fenestra-src

lb clean --purge || true
lb config
lb build 2>&1 | tee build.log
ls -lh ./*.iso
