#!/bin/sh
# Remove the Fenestra apps from macOS (Wine prefixes of converted apps are kept).
rm -rf "$HOME/Applications/Fenestra.app" "$HOME/Applications/Fenestra Task Manager.app" \
       "$HOME/Applications/Fenestra File Explorer.app" "$HOME/Applications/Fenestra Settings.app" \
       "$HOME/Applications/Windows App Converter.app" \
       "$HOME/Library/Application Support/Fenestra/venv" "$HOME/Library/Application Support/Fenestra/src"
echo "Fenestra apps removed."
