#!/usr/bin/env bash
# Installs busy-bee: creates a venv, installs deps, and symlinks
# `dashctl` and `busy-bee` onto PATH.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$REPO_DIR/.venv"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -e "$REPO_DIR"

mkdir -p "$BIN_DIR"
ln -sf "$VENV_DIR/bin/dashctl" "$BIN_DIR/dashctl"
ln -sf "$VENV_DIR/bin/busy-bee" "$BIN_DIR/busy-bee"

mkdir -p "$HOME/.claude-dashboard"

"$VENV_DIR/bin/dashctl" setup-global

echo
echo "Installed. Make sure $BIN_DIR is on PATH."
echo "Run 'busy-bee' to start the menu bar app."
echo "Any project you work in from now on will register itself the"
echo "first time an agent logs status -- no per-project setup needed."
