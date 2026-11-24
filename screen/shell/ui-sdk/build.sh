#!/bin/sh
# Reproducible build of the experiment-only UI SDK bundle.
# No network at compose time: this file is inlined into the teaching frame.
# Re-run: cd screen/shell/ui-sdk && npm ci && ./build.sh
set -eu
cd "$(dirname "$0")"
OUT="../ui-sdk.bundle.js"
META="../ui-sdk.bundle.meta.json"
./node_modules/.bin/esbuild entry.js \
  --bundle --minify --format=iife \
  --target=es2020 --tree-shaking=true \
  --outfile="$OUT"
RAW=$(wc -c < "$OUT" | tr -d ' ')
GZIP=$(gzip -c "$OUT" | wc -c | tr -d ' ')
SHA=$(sha256sum "$OUT" | cut -d' ' -f1)
printf '{\n  "package": "@ui-sdk/web + @ui-sdk/core",\n  "version": "0.1.0-beta.17",\n  "license": "Apache-2.0",\n  "file": "screen/shell/ui-sdk.bundle.js",\n  "raw_bytes": %s,\n  "gzip_bytes": %s,\n  "sha256": "%s"\n}\n' "$RAW" "$GZIP" "$SHA" > "$META"
cat "$META"
