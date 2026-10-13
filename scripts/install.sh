#!/bin/sh
# Install Fenestra on an existing Debian 12+/Ubuntu 22.04+ system.
#   curl -fsSL https://raw.githubusercontent.com/sms2620525-lgtm/os/main/scripts/install.sh | sudo sh
# or, from a checkout:  sudo ./scripts/install.sh
set -e

if [ "$(id -u)" -ne 0 ]; then
    echo "Please run as root: sudo $0" >&2
    exit 1
fi

SRC="$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)"
if [ ! -f "$SRC/fenestra/__init__.py" ]; then
    apt-get update && apt-get install -y git
    SRC=/tmp/fenestra-src
    rm -rf "$SRC"
    git clone --depth 1 https://github.com/sms2620525-lgtm/os.git "$SRC"
fi

echo ">>> Enabling 32-bit packages (needed by Wine for 32-bit Windows programs)"
dpkg --add-architecture i386 || true
apt-get update

echo ">>> Installing packages"
PKGS=""
for p in $(grep -v '^[[:space:]]*#' "$SRC/distro/config/package-lists/fenestra.list.chroot"); do
    # skip packages that do not exist on this distribution/release
    apt-cache show "$p" >/dev/null 2>&1 && PKGS="$PKGS $p"
done
# shellcheck disable=SC2086
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends $PKGS
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends wine32:i386 || true

echo ">>> Installing Fluent GTK and icon themes"
sh "$SRC/scripts/install-themes.sh" || echo "warning: theme download failed (offline?)"

echo ">>> Installing Fenestra"
make -C "$SRC" install PREFIX=/usr

systemctl restart systemd-binfmt 2>/dev/null || true
update-desktop-database /usr/share/applications 2>/dev/null || true
gtk-update-icon-cache -f /usr/share/icons/hicolor 2>/dev/null || true

if [ -d /etc/lightdm ]; then
    install -d /etc/lightdm/lightdm.conf.d
    cp "$SRC/data/lightdm/50-fenestra.conf" /etc/lightdm/lightdm.conf.d/
    cp "$SRC/data/lightdm/lightdm-gtk-greeter.conf" /etc/lightdm/
fi

echo
echo "Fenestra is installed. Log out and choose the 'Fenestra' session on the login screen."
