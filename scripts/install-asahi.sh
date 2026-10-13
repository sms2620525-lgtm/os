#!/bin/sh
# Install Fenestra on an Apple Silicon Mac running Fedora Asahi Remix (bare metal, M1/M2).
#   1. Install Asahi Linux from macOS:  curl https://alx.sh | sh   (choose "Fedora Asahi Remix")
#   2. Boot into Linux, then:           sudo ./scripts/install-asahi.sh
#   3. Log out, pick the "Fenestra" session (X11) on the login screen.
set -e
[ "$(id -u)" -eq 0 ] || { echo "Run as root: sudo $0"; exit 1; }
[ "$(uname -m)" = aarch64 ] || echo "warning: this script is meant for Apple Silicon (aarch64)."
SRC="$(cd "$(dirname "$0")/.." && pwd)"

PKGS="xorg-x11-server-Xorg xorg-x11-xinit openbox picom xcape dex-autostart xdg-user-dirs xdg-utils
      xsettingsd lxpolkit wmctrl network-manager-applet blueman pavucontrol brightnessctl redshift
      power-profiles-daemon python3 python3-pyqt6 python3-psutil python3-xlib python3-dbus make git
      wine winetricks fex-emu muvm cabextract p7zip unzip
      google-noto-sans-fonts google-noto-sans-cjk-fonts google-noto-emoji-color-fonts
      fcitx5 fcitx5-hangul fcitx5-configtool qterminal mousepad galculator ristretto flameshot file-roller"

echo ">>> Installing packages (unavailable ones are skipped)"
# shellcheck disable=SC2086
dnf install -y --skip-unavailable $PKGS 2>/dev/null || dnf install -y --setopt=strict=False $PKGS

echo ">>> Installing Fluent themes"
sh "$SRC/scripts/install-themes.sh" || echo "warning: theme download failed"

echo ">>> Installing Fenestra"
make -C "$SRC" install PREFIX=/usr
systemctl restart systemd-binfmt 2>/dev/null || true
update-desktop-database /usr/share/applications 2>/dev/null || true

cat <<'MSG'

Fenestra is installed.
 * Log out and choose the "Fenestra" session (it runs on X11).
 * Windows x86/x64 programs run through Wine inside muvm + FEX (Asahi's 16K-page kernel needs the
   4K-page micro-VM). Check with:  fenestra-compat host
 * GPU acceleration comes from Asahi's own Mesa drivers (OpenGL 4.6 / Vulkan 1.3).
MSG
