#!/bin/sh
# Build a Fenestra OS live ISO on top of Ubuntu 24.04 LTS (noble), amd64.
# Works on any Ubuntu/Debian host without live-build:
#   sudo apt install debootstrap squashfs-tools xorriso grub-pc-bin grub-efi-amd64-bin mtools dosfstools
#   sudo ./distro/ubuntu/build-iso.sh [workdir]
# Output: <workdir>/fenestra-os-<version>-amd64.iso  (boots on BIOS and UEFI PCs and VMs)
set -e
[ "$(id -u)" -eq 0 ] || { echo "run as root"; exit 1; }
SRC="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="${1:-/var/tmp/fenestra-iso}"
MIRROR="${MIRROR:-http://archive.ubuntu.com/ubuntu/}"
VERSION="$(python3 -c "import sys; sys.path.insert(0, '$SRC'); import fenestra; print(fenestra.__version__)")"
CHROOT="$WORK/chroot"
IMAGE="$WORK/image"
ISO="$WORK/fenestra-os-$VERSION-amd64.iso"

mkdir -p "$WORK"
if [ ! -x "$CHROOT/bin/bash" ]; then
    debootstrap --arch=amd64 --variant=minbase noble "$CHROOT" "$MIRROR"
fi

cleanup() {
    for m in dev/pts dev proc sys run; do umount -lf "$CHROOT/$m" 2>/dev/null || true; done
}
trap cleanup EXIT
mount --bind /dev "$CHROOT/dev"
mount -t devpts devpts "$CHROOT/dev/pts"
mount -t proc proc "$CHROOT/proc"
mount -t sysfs sysfs "$CHROOT/sys"
mount -t tmpfs tmpfs "$CHROOT/run"
cp /etc/resolv.conf "$CHROOT/etc/resolv.conf" 2>/dev/null || true

cat > "$CHROOT/etc/apt/sources.list" <<SRCS
deb $MIRROR noble main restricted universe multiverse
deb $MIRROR noble-updates main restricted universe multiverse
deb $MIRROR noble-security main restricted universe multiverse
SRCS
# Pass the host's apt proxy (if any) into the chroot
[ -n "$http_proxy" ] && echo "Acquire::http::Proxy \"$http_proxy\";" > "$CHROOT/etc/apt/apt.conf.d/90proxy"
# Ubuntu would otherwise pull snap transitional packages for browsers
printf 'Package: snapd\nPin: release a=*\nPin-Priority: -10\n' > "$CHROOT/etc/apt/preferences.d/no-snap"

rm -rf "$CHROOT/opt/fenestra-src"
mkdir -p "$CHROOT/opt/fenestra-src"
(cd "$SRC" && tar --exclude=./.git --exclude='*.bundle' --exclude=./distro/ubuntu/work -cf - .) | tar -xf - -C "$CHROOT/opt/fenestra-src"

cat > "$CHROOT/tmp/setup.sh" <<'SETUP'
#!/bin/sh
set -e
export DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8
echo fenestra > /etc/hostname
dpkg --add-architecture i386
apt-get update
apt-get install -y --no-install-recommends \
    linux-generic casper initramfs-tools systemd-sysv sudo locales tzdata keyboard-configuration \
    network-manager network-manager-gnome ca-certificates curl wget less nano dbus-x11 \
    xserver-xorg xserver-xorg-video-all xserver-xorg-input-all x11-xserver-utils xinit \
    openbox picom xcape dex xdg-user-dirs xdg-utils xsettingsd wmctrl lightdm lightdm-gtk-greeter \
    lxpolkit pulseaudio pavucontrol brightnessctl redshift policykit-1 \
    python3 python3-pyqt6 python3-psutil python3-xlib python3-dbus make git \
    wine wine64 wine32:i386 winetricks cabextract p7zip-full unzip \
    fonts-noto-core fonts-noto-cjk fonts-noto-color-emoji fonts-inter \
    fcitx5 fcitx5-hangul \
    qterminal mousepad galculator ristretto falkon flameshot file-roller gvfs-backends \
    spice-vdagent qemu-guest-agent open-vm-tools-desktop mesa-utils x11-utils console-setup kbd
locale-gen en_US.UTF-8 ko_KR.UTF-8
cd /opt/fenestra-src
make install PREFIX=/usr
install -d /etc/lightdm/lightdm.conf.d
cp data/lightdm/50-fenestra.conf /etc/lightdm/lightdm.conf.d/
cp data/lightdm/lightdm-gtk-greeter.conf /etc/lightdm/
# Live session: log straight into Fenestra
cat > /etc/lightdm/lightdm.conf.d/60-live-autologin.conf <<AL
[Seat:*]
autologin-user=fenestra
autologin-session=fenestra
AL
printf 'export USERNAME="fenestra"\nexport USERFULLNAME="Fenestra Live"\nexport HOST="fenestra"\nexport BUILD_SYSTEM="Ubuntu"\nexport FLAVOUR="Fenestra"\n' > /etc/casper.conf
update-alternatives --set x-terminal-emulator /usr/bin/qterminal 2>/dev/null || true
update-alternatives --install /usr/bin/x-session-manager x-session-manager /usr/bin/fenestra-session 90
update-alternatives --install /usr/bin/x-www-browser x-www-browser /usr/bin/falkon 90
cat > /etc/os-release <<OSR
PRETTY_NAME="Fenestra OS (based on Ubuntu 24.04 LTS)"
NAME="Fenestra OS"
ID=fenestra
ID_LIKE="ubuntu debian"
VERSION_CODENAME=noble
UBUNTU_CODENAME=noble
HOME_URL="https://github.com/sms2620525-lgtm/os"
OSR
update-desktop-database /usr/share/applications || true
gtk-update-icon-cache -f /usr/share/icons/hicolor || true
update-initramfs -u -k all
apt-get clean
rm -rf /opt/fenestra-src /var/lib/apt/lists/* /tmp/* /etc/apt/apt.conf.d/90proxy
SETUP
chroot "$CHROOT" sh /tmp/setup.sh
cleanup
trap - EXIT

echo ">>> Building image tree"
rm -rf "$IMAGE"
mkdir -p "$IMAGE/casper" "$IMAGE/boot/grub"
cp "$(ls "$CHROOT"/boot/vmlinuz-* | sort -V | tail -1)" "$IMAGE/casper/vmlinuz"
cp "$(ls "$CHROOT"/boot/initrd.img-* | sort -V | tail -1)" "$IMAGE/casper/initrd"
mksquashfs "$CHROOT" "$IMAGE/casper/filesystem.squashfs" -noappend -comp xz -e boot -wildcards -e 'proc/*' -e 'sys/*' -e 'dev/*' -e 'run/*'
du -sx --block-size=1 "$CHROOT" | cut -f1 > "$IMAGE/casper/filesystem.size"
touch "$IMAGE/fenestra.marker"
cat > "$IMAGE/boot/grub/grub.cfg" <<GRUB
search --set=root --file /fenestra.marker
insmod all_video
set default=0
set timeout=5
menuentry "Fenestra OS $VERSION (live)" {
    linux /casper/vmlinuz boot=casper quiet splash ---
    initrd /casper/initrd
}
menuentry "Fenestra OS $VERSION (live, safe graphics)" {
    linux /casper/vmlinuz boot=casper nomodeset ---
    initrd /casper/initrd
}
menuentry "Fenestra OS $VERSION (live, 한국어)" {
    linux /casper/vmlinuz boot=casper locale=ko_KR.UTF-8 quiet splash ---
    initrd /casper/initrd
}
GRUB
grub-mkrescue -o "$ISO" "$IMAGE" -- -volid FENESTRA
ls -lh "$ISO"
sha256sum "$ISO" > "$ISO.sha256"
