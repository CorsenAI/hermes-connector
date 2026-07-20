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

sh "$ROOT/scripts/install.sh" \
  --hermes-home "$TEST_ROOT" \
  --no-enable \
  --no-show-code

PLUGIN="$TEST_ROOT/plugins/hermes-connector"
test -f "$PLUGIN/plugin.yaml"
grep -q "version: 0.2.0" "$PLUGIN/plugin.yaml"
printf '%s\n' "POSIX companion install passed: $PLUGIN"
