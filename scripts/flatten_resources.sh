#!/usr/bin/env bash
#
# Flatten a nested resources tree into a self-contained sibling directory,
# prefixing each file with its subdirectory path ("/" -> "_"):
#
#   resources/data.lsdb.io/gaia.xml  ->  _resources/data.lsdb.io_gaia.xml
#
# If two source paths flatten to the same name, it prints both and aborts
# WITHOUT touching the destination.
#
# Usage: flatten_resources.sh <src-dir> <dst-dir>

set -euo pipefail

SRC=${1:?usage: flatten_resources.sh <src-dir> <dst-dir>}
DST=${2:?usage: flatten_resources.sh <src-dir> <dst-dir>}
SRC=${SRC%/}   # strip any trailing slash
DST=${DST%/}

[[ -d "$SRC" ]] || { echo "flatten: source '$SRC' is not a directory" >&2; exit 1; }

# Build into a temp sibling of DST, then swap in atomically at the end.
TMP=$(mktemp -d "${DST}.tmp.XXXXXX")
trap 'rm -rf "$TMP"' EXIT

declare -A seen
conflict=0

while IFS= read -r -d '' f; do
  rel=${f#"$SRC"/}       # data.lsdb.io/gaia.xml
  flat=${rel//\//_}      # data.lsdb.io_gaia.xml
  if [[ -n "${seen[$flat]:-}" ]]; then
    echo "CONFLICT: '$flat' produced by both '$rel' and '${seen[$flat]}'" >&2
    conflict=1
    continue
  fi
  seen[$flat]=$rel
  cp -p "$f" "$TMP/$flat"
done < <(find "$SRC" -type f -name '*.xml' -print0)

if (( conflict )); then
  echo "flatten: aborting due to name collisions; '$DST' left unchanged." >&2
  exit 1
fi

rm -rf "$DST"
mv "$TMP" "$DST"
trap - EXIT

echo "flatten: wrote $(find "$DST" -maxdepth 1 -type f | wc -l) files to '$DST'"