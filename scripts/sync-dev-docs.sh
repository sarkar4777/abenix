#!/usr/bin/env bash
# Sync docs/ into apps/web/public/dev-docs/ so the in-app viewer at /docs
# serves the same content GitHub does. Run after any edit under docs/.
#
# Usage: bash scripts/sync-dev-docs.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/docs"
DST="$ROOT/apps/web/public/dev-docs"

if [ ! -d "$SRC" ]; then
  echo "docs/ not found at $SRC" >&2
  exit 1
fi

rm -rf "$DST"
mkdir -p "$DST"

# Copy only the .md files + manifest, skip TRAJECTORY_MEMORY.md and assets/screenshots.
(cd "$SRC" && find . -type f -name '*.md' ! -name 'TRAJECTORY_MEMORY.md' -print0) \
  | while IFS= read -r -d '' f; do
    rel="${f#./}"
    mkdir -p "$DST/$(dirname "$rel")"
    cp "$SRC/$rel" "$DST/$rel"
  done

# Preserve the existing manifest if present (it ships with the page) — only copy
# if a fresh one exists under docs/.
[ -f "$SRC/manifest.json" ] && cp "$SRC/manifest.json" "$DST/manifest.json"

printf 'Synced %s markdown files into %s\n' \
  "$(find "$DST" -name '*.md' | wc -l | tr -d ' ')" \
  "$DST"
