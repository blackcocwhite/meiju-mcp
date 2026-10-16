#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"
if [ -n "${MEIJU_GO_BINARY:-}" ]; then
  exec "$MEIJU_GO_BINARY" "$@"
elif [ -x "$root/../.cache/go-toolchain/go/bin/go" ]; then
  exec "$root/../.cache/go-toolchain/go/bin/go" "$@"
else
  exec go "$@"
fi
