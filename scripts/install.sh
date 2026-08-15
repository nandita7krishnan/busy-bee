#!/usr/bin/env bash
# Installs busy-bee: creates a venv, installs deps, and symlinks
# `dashctl` and `busy-bee` onto PATH.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$REPO_DIR/.venv"

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -e "$REPO_DIR"

# Pick a bin dir that's actually on PATH already -- ~/.local/bin is the
# conventional default, but plenty of machines (this one included)
# never added it to PATH, which makes dashctl silently unusable from
# any new terminal. Prefer wherever `claude` itself is installed (same
# convention, and guaranteed relevant on a machine running Claude
# Code); then any other writable dir already on PATH; only fall back
# to ~/.local/bin (with an explicit warning) if nothing writable was
# found on PATH at all.
BIN_DIR="${BIN_DIR:-}"
if [ -z "$BIN_DIR" ]; then
    claude_path="$(command -v claude || true)"
    if [ -n "$claude_path" ] && [ -w "$(dirname "$claude_path")" ]; then
        BIN_DIR="$(dirname "$claude_path")"
    fi
fi
if [ -z "$BIN_DIR" ]; then
    IFS=':' read -ra path_dirs <<< "$PATH"
    for dir in "${path_dirs[@]}"; do
        if [ -w "$dir" ]; then
            BIN_DIR="$dir"
            break
        fi
    done
fi
if [ -z "$BIN_DIR" ]; then
    BIN_DIR="$HOME/.local/bin"
    NEEDS_PATH_WARNING=1
fi

mkdir -p "$BIN_DIR"
ln -sf "$VENV_DIR/bin/dashctl" "$BIN_DIR/dashctl"
ln -sf "$VENV_DIR/bin/busy-bee" "$BIN_DIR/busy-bee"

mkdir -p "$HOME/.claude-dashboard"

"$VENV_DIR/bin/dashctl" setup-global

bash "$REPO_DIR/scripts/build_app_bundle.sh"

echo
echo "Installed dashctl and busy-bee into $BIN_DIR."
if [ "${NEEDS_PATH_WARNING:-0}" = "1" ]; then
    echo "WARNING: $BIN_DIR doesn't look like it's on PATH. Add it (e.g. in"
    echo "~/.zshrc: export PATH=\"\$HOME/.local/bin:\$PATH\") or dashctl won't"
    echo "be found from new terminals."
fi
echo "Launch it from Spotlight/Launchpad as \"Busy Bee\", or run 'busy-bee'"
echo "from a terminal -- both start the same menu bar app."
echo "Any project you work in from now on will register itself the"
echo "first time an agent logs status -- no per-project setup needed."
