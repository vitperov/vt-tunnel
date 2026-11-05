#!/usr/bin/env bash
# make_src_zip.sh — build a clean source zip of a package directory
# (default: gui) for sharing or running on another machine.
#
# Excludes VCS metadata, build output, virtualenvs and caches; keeps
# source, packaging files, docs and the lockfile. After building, the
# archive is listed and the script fails if any excluded pattern is
# still inside, so the output is verified by construction.
#
# Usage (from the repo root):
#   tools/make_src_zip.sh [pkg-dir] [output.zip]

set -euo pipefail

command -v zip >/dev/null 2>&1 || { echo "error: zip is required" >&2; exit 2; }

PKG=${1:-gui}
[ -d "$PKG" ] || { echo "error: no package directory: $PKG" >&2; exit 2; }
PKG=$(cd "$PKG" && pwd)

OUT=${2:-"$PKG/build/$(basename "$PKG")-src.zip"}
OUT=$(realpath -m "$OUT")
mkdir -p "$(dirname "$OUT")"
rm -f "$OUT"

EXCLUDES=(
  -x '.git/*' '*/.git/*'
  -x 'build/*' '*/build/*'
  -x '.venv/*' '*/.venv/*' 'venv/*' '*/venv/*'
  -x '*__pycache__/*' '*.pyc'
  -x '.pytest_cache/*' '*/.pytest_cache/*'
  -x '.mypy_cache/*' '*/.mypy_cache/*'
  -x '.ruff_cache/*' '*/.ruff_cache/*'
  -x '*.egg-info/*' '*/.egg-info/*'
)

# never include the archive being written, if it lands inside the tree
PARENT=$(dirname "$PKG")
BASE=$(basename "$PKG")
SELF_EXCLUDE=()
case "$OUT" in
  "$PARENT"/*) SELF_EXCLUDE=(-x "${OUT#"$PARENT"/}") ;;
esac

(
  cd "$PARENT"
  zip -r "$OUT" "$BASE" "${EXCLUDES[@]}" "${SELF_EXCLUDE[@]}" >/dev/null
)

LEAK=$(unzip -Z1 "$OUT" | grep -E \
  '(^|/)\.git(/|$)|(^|/)build(/|$)|(^|/)\.venv(/|$)|(^|/)venv(/|$)|__pycache__|\.pyc$|\.pytest_cache|\.mypy_cache|\.ruff_cache|\.egg-info' || true)
if [ -n "$LEAK" ]; then
  echo "error: excluded paths leaked into $OUT:" >&2
  printf '%s\n' "$LEAK" | sort -u | sed 's/^/  /' >&2
  rm -f "$OUT"
  exit 1
fi

NFILES=$(unzip -Z1 "$OUT" | grep -v '/$' | wc -l)
echo "OK: $OUT ($(du -h "$OUT" | cut -f1), $NFILES files, listing verified clean)"