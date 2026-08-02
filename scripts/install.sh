#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INSTALLER="$SCRIPT_DIR/install.py"
if [ ! -f "$INSTALLER" ]; then INSTALLER="$SCRIPT_DIR/install_companion.py"; fi
PYTHON_BIN=""

python_is_supported() {
  [ -n "$1" ] && [ -x "$1" ] &&
    "$1" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' >/dev/null 2>&1
}

if command -v hermes >/dev/null 2>&1; then
  HERMES_BIN=$(command -v hermes)
  case "$HERMES_BIN" in
    /*) ;;
    *) HERMES_BIN=$(CDPATH= cd -- "$(dirname -- "$HERMES_BIN")" && pwd)/$(basename -- "$HERMES_BIN") ;;
  esac
  while [ -L "$HERMES_BIN" ]; do
    LINK_TARGET=$(readlink "$HERMES_BIN")
    case "$LINK_TARGET" in
      /*) HERMES_BIN="$LINK_TARGET" ;;
      *) HERMES_BIN="$(dirname -- "$HERMES_BIN")/$LINK_TARGET" ;;
    esac
  done
  HERMES_BIN_DIR=$(CDPATH= cd -- "$(dirname -- "$HERMES_BIN")" && pwd)
  if python_is_supported "$HERMES_BIN_DIR/python3"; then PYTHON_BIN="$HERMES_BIN_DIR/python3"
  elif python_is_supported "$HERMES_BIN_DIR/python"; then PYTHON_BIN="$HERMES_BIN_DIR/python"
  elif [ -f "$HERMES_BIN" ]; then
    IFS= read -r SHEBANG < "$HERMES_BIN" || SHEBANG=""
    case "$SHEBANG" in
      '#!'/*)
        SHEBANG_PYTHON=${SHEBANG#\#!}
        SHEBANG_PYTHON=${SHEBANG_PYTHON%% *}
        if python_is_supported "$SHEBANG_PYTHON"; then PYTHON_BIN="$SHEBANG_PYTHON"; fi
        ;;
    esac
  fi
fi
if [ -z "$PYTHON_BIN" ]; then
  for PYTHON_NAME in python3 python; do
    PYTHON_CANDIDATE=$(command -v "$PYTHON_NAME" || true)
    if python_is_supported "$PYTHON_CANDIDATE"; then
      PYTHON_BIN="$PYTHON_CANDIDATE"
      break
    fi
  done
fi
if [ -z "$PYTHON_BIN" ]; then
  echo "Python 3.10 or newer was not found." >&2
  exit 1
fi
exec "$PYTHON_BIN" "$INSTALLER" "$@"
