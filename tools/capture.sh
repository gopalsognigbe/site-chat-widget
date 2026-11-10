#!/usr/bin/env bash
# Headless Chrome capture. Usage: tools/capture.sh <url> <out.png> [width] [height]
# Motion is settled by emulating prefers-reduced-motion through a fresh profile flag.
set -euo pipefail
URL="$1"; OUT="$2"; W="${3:-1440}"; H="${4:-900}"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE="$(mktemp -d)"
"$CHROME" --headless=new --disable-gpu --hide-scrollbars --user-data-dir="$PROFILE" \
  --force-prefers-reduced-motion --window-size="$W,$H" --virtual-time-budget=6000 \
  --screenshot="$OUT" "$URL" >/dev/null 2>&1
rm -rf "$PROFILE"
echo "$OUT"
