#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INSTALLER="$SCRIPT_DIR/install.py"
if [ ! -f "$INSTALLER" ]; then INSTALLER="$SCRIPT_DIR/install_companion.py"; fi
exec python3 "$INSTALLER" "$@"
