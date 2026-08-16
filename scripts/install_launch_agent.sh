#!/usr/bin/env bash
# Installs a launchd agent that starts busy-bee at login and restarts
# it automatically whenever it's not running (including after using
# the tray menu's Quit -- see README's Known limitations for why that
# tradeoff is intentional here).
#
# This exists because launching busy-bee as a normal macOS .app
# (double-click, Spotlight, Launchpad) reliably fails: Launch Services
# registers that launch path in a way that makes Control Center's
# status-item XPC service refuse the connection every time (confirmed
# live via Console -- "scene activation failed",
# BSServiceConnectionErrorDomain). A launchd agent isn't launched
# through that Launch-Services "app" path at all, so it doesn't hit
# the same failure -- verified working repeatedly.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="dev.busybee.app"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$REPO_DIR/.venv/bin/busy-bee</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>5</integer>
    <key>StandardOutPath</key>
    <string>/tmp/busybee-agent.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/busybee-agent.log</string>
</dict>
</plist>
PLIST

launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo "Installed and started the busy-bee LaunchAgent ($PLIST_PATH)."
echo "It starts automatically at login and restarts itself if it ever"
echo "stops -- look for the 🐝 in your menu bar now."
echo "To fully stop it (it won't restart until you load it again):"
echo "  launchctl unload \"$PLIST_PATH\""
