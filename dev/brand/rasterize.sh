#!/bin/bash
# Raster copies of the brand SVGs, for the places that will not take a vector:
# the social card and the home-screen icon. (The masthead art stays SVG; a
# WebP of it at 3x was measured and came out larger than the brotli'd vector.)
#
#   dev/brand/rasterize.sh
#
# Needs a headless Chromium (the one Playwright installs is found
# automatically; override with CHROME_PATH). Run after build_brand_assets.py
# whenever the artwork changes, then bump the ?v= on the tags that load it:
# vercel.json serves images as immutable for 30 days.

set -euo pipefail
cd "$(dirname "$0")/../.."

CHROME="${CHROME_PATH:-$( { find "$HOME/Library/Caches/ms-playwright" "$HOME/.cache/ms-playwright" \
    -name chrome-headless-shell -type f 2>/dev/null || true; } | sort | tail -1)}"
[ -x "$CHROME" ] || { echo "No headless Chromium found; set CHROME_PATH"; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
BRAND="file://$PWD/docs/brand"

shot() {  # shot <name> <width> <height> <background> <body html>
    printf '<html><body style="margin:0;background:%s">%s</body></html>' "$4" "$5" > "$TMP/$1.html"
    "$CHROME" --headless --disable-gpu --hide-scrollbars --allow-file-access-from-files \
        --default-background-color=00000000 --window-size="$2,$3" \
        --screenshot="$TMP/$1.png" "file://$TMP/$1.html" >/dev/null 2>&1 </dev/null
}

# Social card, 1200x630 on the logo's own cream.
shot og 1200 630 '#FCE2B6' "<img src='$BRAND/logo.svg' style='height:590px;display:block;margin:20px auto 0'>"
cp "$TMP/og.png" docs/brand/og-image.png

# Home-screen and legacy favicons. iOS rounds the corners itself.
ICON="<div style='width:100%;height:100%;background:#FCB91A'><img src='file://$PWD/docs/favicon.svg' style='width:100%;height:100%;display:block'></div>"
shot touch 180 180 '#FCB91A' "<div style='width:180px;height:180px'>$ICON</div>"
shot fav 32 32 transparent "<img src='file://$PWD/docs/favicon.svg' style='width:32px;height:32px;display:block'>"
cp "$TMP/touch.png" docs/brand/apple-touch-icon.png
cp "$TMP/fav.png" docs/brand/favicon-32.png

# The rasters carry their origin in a PNG tEXt chunk. A re-run drops it; put it
# back with: impeccable embed-prompt docs/brand/<file>.png --prompt "<origin>"
# (check with: impeccable embed-prompt --scan docs/brand)
ls -la docs/brand | awk 'NR>1 {printf "  %-26s %7.1f KB\n", $NF, $5/1024}'
