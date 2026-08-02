#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TMP_BASE=${TMPDIR:-/tmp}
TMP_BASE=${TMP_BASE%/}
TEST_ROOT=$(mktemp -d "$TMP_BASE/hermes-connector-install-XXXXXX")

cleanup() {
  case "$TEST_ROOT" in
    "$TMP_BASE"/hermes-connector-install-*) rm -rf -- "$TEST_ROOT" ;;
    *) printf '%s\n' "Refusing to remove unexpected test path: $TEST_ROOT" >&2; exit 1 ;;
  esac
}
trap cleanup EXIT HUP INT TERM

mkdir -p "$TEST_ROOT/profiles/work"
printf '%s\n' 'plugins:' '  enabled: []' > "$TEST_ROOT/profiles/work/config.yaml"

# A pipx-style shim must resolve to the Python beside the real Hermes script,
# not an unrelated or too-old system interpreter earlier on PATH.
FAKE_VENV="$TEST_ROOT/fake-venv/bin"
SHIM_BIN="$TEST_ROOT/shim-bin"
POISON_BIN="$TEST_ROOT/poison-bin"
mkdir -p "$FAKE_VENV" "$SHIM_BIN" "$POISON_BIN"
ln -s "$(command -v python3)" "$FAKE_VENV/python"
printf '%s\n' '#!/usr/bin/env sh' 'exit 0' > "$FAKE_VENV/hermes"
chmod +x "$FAKE_VENV/hermes"
ln -s ../fake-venv/bin/hermes "$SHIM_BIN/hermes"
printf '%s\n' '#!/usr/bin/env sh' 'exit 97' > "$POISON_BIN/python3"
printf '%s\n' '#!/usr/bin/env sh' 'exit 97' > "$POISON_BIN/python"
chmod +x "$POISON_BIN/python3" "$POISON_BIN/python"

PATH="$SHIM_BIN:$POISON_BIN:$PATH" sh "$ROOT/scripts/install.sh" \
  --hermes-home "$TEST_ROOT" \
  --no-enable \
  --no-show-code

PLUGIN="$TEST_ROOT/plugins/hermes-connector"
PROFILE_PLUGIN="$TEST_ROOT/profiles/work/plugins/hermes-connector"
test -f "$PLUGIN/plugin.yaml"
test -f "$PROFILE_PLUGIN/plugin.yaml"
grep -q "version: 0.2.1" "$PLUGIN/plugin.yaml"
grep -q "version: 0.2.1" "$PROFILE_PLUGIN/plugin.yaml"
printf '%s\n' "POSIX companion install passed: $PLUGIN and $PROFILE_PLUGIN"
