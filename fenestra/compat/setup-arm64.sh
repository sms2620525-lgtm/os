#!/bin/sh
# Install Hangover (Wine for ARM64 with FEX/box64 x86 emulation) on Debian/Ubuntu ARM64.
# Used by: sudo fenestra-compat setup-arm   (and by the ARM64 ISO build)
set -e
[ "$(uname -m)" = "aarch64" ] || { echo "This is only needed on ARM64 (aarch64) machines."; exit 0; }
[ "$(id -u)" -eq 0 ] || { echo "Run as root: sudo $0"; exit 1; }

. /etc/os-release
CODENAME="${VERSION_CODENAME:-bookworm}"
case "$ID" in
    debian) PATTERN="debian[0-9]*_${CODENAME}_arm64" ;;
    ubuntu) PATTERN="ubuntu[0-9]*_${CODENAME}_arm64" ;;
    *) echo "Unsupported distribution '$ID'. On Fedora Asahi use: sudo dnf install fex-emu muvm wine"; exit 1 ;;
esac

apt-get update
apt-get install -y curl ca-certificates tar
URL="$(curl -fsSL https://api.github.com/repos/AndreRH/hangover/releases/latest \
      | grep -o '"browser_download_url": *"[^"]*"' | cut -d'"' -f4 | grep -E "$PATTERN" | head -n1)"
if [ -z "$URL" ]; then
    echo "No Hangover build found for $ID $CODENAME. See https://github.com/AndreRH/hangover/releases"
    exit 1
fi
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
echo "Downloading $URL"
curl -fL "$URL" -o "$TMP/hangover.tar"
tar -xf "$TMP/hangover.tar" -C "$TMP"
# shellcheck disable=SC2046
apt-get install -y $(find "$TMP" -name "*.deb")
apt-get install -y winetricks cabextract || true
echo "Hangover installed: x86 and x64 Windows programs now run through Wine + FEX."
