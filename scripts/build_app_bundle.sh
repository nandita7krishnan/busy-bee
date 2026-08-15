#!/usr/bin/env bash
# Wraps the installed `busy-bee` venv command in a minimal .app bundle
# so it's launchable from Spotlight/Launchpad like any other app --
# no Terminal needed. This is a thin wrapper, not a frozen/py2app
# build: it just execs the existing venv, so it always reflects
# whatever's currently installed there (rebuild after code changes by
# re-running this script, or just re-run install.sh which calls it).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_BUSYBEE="$REPO_DIR/.venv/bin/busy-bee"
APP_DIR="${APP_DIR:-/Applications/Busy Bee.app}"

mkdir -p "$APP_DIR/Contents/MacOS"

cat > "$APP_DIR/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>Busy Bee</string>
    <key>CFBundleDisplayName</key>
    <string>Busy Bee</string>
    <key>CFBundleIdentifier</key>
    <string>dev.busybee.app</string>
    <key>CFBundleVersion</key>
    <string>0.1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>0.1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleExecutable</key>
    <string>BusyBee</string>
    <key>LSUIElement</key>
    <true/>
    <key>LSMinimumSystemVersion</key>
    <string>10.13</string>
</dict>
</plist>
PLIST

cat > "$APP_DIR/Contents/MacOS/BusyBee" <<LAUNCHER
#!/bin/bash
exec "$VENV_BUSYBEE"
LAUNCHER
chmod +x "$APP_DIR/Contents/MacOS/BusyBee"

# Nudge Spotlight/Launch Services to pick it up immediately instead of
# waiting for the next periodic scan.
/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister -f "$APP_DIR" 2>/dev/null || true
mdimport "$APP_DIR" 2>/dev/null || true

echo "Installed \"Busy Bee.app\" -- launch it from Spotlight, Launchpad, or double-click in $APP_DIR."
