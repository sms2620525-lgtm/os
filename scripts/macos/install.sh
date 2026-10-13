#!/bin/sh
# Install Fenestra apps natively on macOS (Apple Silicon M1/M2/M3 or Intel).
#   ./scripts/macos/install.sh            # apps only
#   ./scripts/macos/install.sh --wine     # also install Rosetta 2 + Wine (to run .exe files)
# Creates in ~/Applications:
#   Fenestra.app (the Windows 11 style desktop in a window), Task Manager, File Explorer,
#   Settings and Windows App Converter.
set -e
[ "$(uname)" = Darwin ] || { echo "This script is for macOS."; exit 1; }
SRC="$(cd "$(dirname "$0")/../.." && pwd)"
SUPPORT="$HOME/Library/Application Support/Fenestra"
VENV="$SUPPORT/venv"
APPS="$HOME/Applications"

if ! command -v brew >/dev/null; then
    echo "Homebrew is required: https://brew.sh"
    echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
    exit 1
fi

echo ">>> Python 3.12 (the macOS system Python is too old)"
brew list python@3.12 >/dev/null 2>&1 || brew install python@3.12
PY="$(brew --prefix python@3.12)/bin/python3.12"

echo ">>> Python environment"
mkdir -p "$SUPPORT"
rm -rf "$SUPPORT/src"
cp -R "$SRC" "$SUPPORT/src"
"$PY" -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip >/dev/null
"$VENV/bin/pip" install -r "$SUPPORT/src/requirements-macos.txt"

if [ "$1" = "--wine" ]; then
    if [ "$(uname -m)" = arm64 ]; then
        echo ">>> Rosetta 2 (runs x86/x64 Windows code on Apple Silicon)"
        softwareupdate --install-rosetta --agree-to-license || true
    fi
    echo ">>> Wine + winetricks"
    brew install --cask --no-quarantine wine-stable || true
    brew install winetricks || true
fi

echo ">>> Creating apps in $APPS"
mkdir -p "$APPS"
make_app() {   # name module icon [args]
    app="$APPS/$1.app"
    rm -rf "$app"
    mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
    cat > "$app/Contents/MacOS/launcher" <<SH
#!/bin/sh
export PYTHONPATH="$SUPPORT/src"
exec "$VENV/bin/python" -m $2 $4 "\$@"
SH
    chmod +x "$app/Contents/MacOS/launcher"
    PYTHONPATH="$SUPPORT/src" QT_QPA_PLATFORM=offscreen "$VENV/bin/python" -m fenestra.common.icons \
        --icns "$3" "$app/Contents/Resources/AppIcon.icns" >/dev/null
    cat > "$app/Contents/Info.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>$1</string>
  <key>CFBundleIdentifier</key><string>org.fenestra.$3</string>
  <key>CFBundleExecutable</key><string>launcher</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PL
}
make_app "Fenestra" fenestra.shell logo --windowed
make_app "Fenestra Task Manager" fenestra.taskmgr taskmgr
make_app "Fenestra File Explorer" fenestra.explorer explorer
make_app "Fenestra Settings" fenestra.settings settings
make_app "Windows App Converter" fenestra.compat compat gui

echo
echo "Done. Open ~/Applications/Fenestra.app (or Windows App Converter.app to run .exe files)."
[ "$1" = "--wine" ] || echo "To run Windows programs too: $0 --wine"
