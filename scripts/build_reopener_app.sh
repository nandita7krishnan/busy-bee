#!/usr/bin/env bash
# Builds "Open Busy Bee.app" -- a tiny GUI-launchable app whose only
# job is telling launchd to (re)start the real busy-bee LaunchAgent.
#
# Why this exists, and why it's a separate app rather than just making
# busy-bee itself double-clickable again: launching busy-bee directly
# through Launch Services (double-click, Spotlight, Launchpad) reliably
# breaks its status-item creation (see README's Known limitations --
# Control Center's status-item XPC service refuses the connection
# every time for a Launch-Services-launched instance of this
# particular app). Quitting busy-bee from its own tray menu is
# intentionally NOT auto-restarted (no LaunchAgent KeepAlive, per
# explicit preference), which means once quit, launchd needs to be
# told to start it again -- normally a `launchctl` terminal command.
# This app exists purely to run that command with a double-click. It
# never touches AppKit/rumps/pywebview itself, so its own (also
# Launch-Services-launched) process never tries to create a status
# item -- only the actual busy-bee process does, and that one is
# started via launchd, a completely different path that works.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="dev.busybee.app"
APP_DIR="${APP_DIR:-/Applications/Open Busy Bee.app}"

mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"

cat > "$APP_DIR/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>Open Busy Bee</string>
    <key>CFBundleDisplayName</key>
    <string>Open Busy Bee</string>
    <key>CFBundleIdentifier</key>
    <string>dev.busybee.opener</string>
    <key>CFBundleVersion</key>
    <string>0.1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>0.1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleExecutable</key>
    <string>OpenBusyBee</string>
    <key>CFBundleIconFile</key>
    <string>icon.icns</string>
    <key>LSUIElement</key>
    <true/>
    <key>LSBackgroundOnly</key>
    <true/>
</dict>
</plist>
PLIST

# Build icon.icns from the same bee art used everywhere else (the
# tray icon, the Dock icon), so this app looks recognizable in
# Finder/Launchpad/Dock instead of a generic icon.
BEE_PNG="$("$REPO_DIR/.venv/bin/python" -c "from busy_bee.icon import render_plain_bee; print(render_plain_bee())")"
ICONSET="$(mktemp -d)/icon.iconset"
mkdir -p "$ICONSET"
for spec in "16:icon_16x16" "32:icon_16x16@2x" "32:icon_32x32" "64:icon_32x32@2x" \
            "128:icon_128x128" "256:icon_128x128@2x" "256:icon_256x256" \
            "512:icon_256x256@2x" "512:icon_512x512" "1024:icon_512x512@2x"; do
    px="${spec%%:*}"
    name="${spec##*:}"
    sips -z "$px" "$px" "$BEE_PNG" --out "$ICONSET/$name.png" >/dev/null 2>&1
done
iconutil -c icns "$ICONSET" -o "$APP_DIR/Contents/Resources/icon.icns"
rm -rf "$(dirname "$ICONSET")"

cat > "$APP_DIR/Contents/MacOS/OpenBusyBee" <<LAUNCHER
#!/bin/bash
UID_NUM=\$(id -u)
launchctl kickstart -k "gui/\$UID_NUM/$LABEL" 2>/dev/null \\
  || launchctl load "\$HOME/Library/LaunchAgents/$LABEL.plist" 2>/dev/null
LAUNCHER
chmod +x "$APP_DIR/Contents/MacOS/OpenBusyBee"

/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister -f "$APP_DIR" 2>/dev/null || true

echo "Built \"Open Busy Bee.app\" in $APP_DIR."
echo "Launch it from Spotlight/Launchpad/Dock any time busy-bee has"
echo "been quit and you want it running again."
