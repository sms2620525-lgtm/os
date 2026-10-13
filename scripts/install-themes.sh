#!/bin/sh
# Download and install the (GPL-3.0) Fluent GTK theme and Fluent icon theme by vinceliuice.
set -e
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git clone --depth 1 https://github.com/vinceliuice/Fluent-gtk-theme.git "$TMP/gtk"
git clone --depth 1 https://github.com/vinceliuice/Fluent-icon-theme.git "$TMP/icons"
(cd "$TMP/gtk" && ./install.sh -d /usr/share/themes --tweaks round noborder) || (cd "$TMP/gtk" && ./install.sh -d /usr/share/themes)
(cd "$TMP/icons" && ./install.sh -d /usr/share/icons)
