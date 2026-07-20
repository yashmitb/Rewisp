#!/bin/zsh
# Build a distributable Rewisp DMG: app with the daemon bundled inside,
# a one-double-click installer, and an Applications shortcut.
set -e
cd "$(dirname "$0")/.."

echo "── building app ──"
(cd ui && ./build.sh)

# read the version AFTER the build — the pre-existing bundle may be stale
VERSION=$(defaults read "$(pwd)/ui/Rewisp.app/Contents/Info" CFBundleShortVersionString 2>/dev/null || echo "0.1.0")

echo "── bundling the Python runtime into the app ──"
./scripts/bundle_python.sh

echo "── bundling daemon into the app ──"
RES="ui/Rewisp.app/Contents/Resources/daemon"
rm -rf "$RES"
mkdir -p "$RES"
cp -R rewisp "$RES/rewisp"
find "$RES" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
cp scripts/install.sh "$RES/install.sh"
chmod +x "$RES/install.sh"
# NOT --deep: it re-signs the bundled helper and strips its identifier back to
# "-", which destroys the Screen Recording grant (see bundle_python.sh). Sign the
# outer bundle only; the helper already carries its own stable signature, and
# sealing the app records it as-is.
codesign --force --sign - ui/Rewisp.app

echo "── staging ──"
STAGE=$(mktemp -d)
cp -R ui/Rewisp.app "$STAGE/"
ln -s /Applications "$STAGE/Applications"
# Just the app and the Applications shortcut — the classic two-icon DMG.
# No "Install Rewisp.command": since v0.12 the app provisions its own background
# helper on first launch, so shipping an installer people feel obliged to run is
# pure confusion (and it contradicts the install page). install.sh still ships
# INSIDE the bundle as the fallback the "Finish setup" button invokes.

DMG="dist/Rewisp-$VERSION.dmg"
mkdir -p dist
rm -f "$DMG"

# Branded window: background image + fixed icon positions, the way a normal Mac
# app installs. Build read-write first so Finder can save the layout, then
# compress. If Finder automation is unavailable the plain DMG still ships.
echo "── laying out the DMG window ──"
mkdir -p "$STAGE/.background"
python3 scripts/dmg_background.py "$STAGE/.background/bg" >/dev/null 2>&1 || \
  echo "  (background render skipped)"

# Combine the 1x and 2x renders into one HiDPI TIFF. Finder scales a plain PNG
# background to the window size in POINTS, so on a Retina display a 720x480 PNG
# gets upscaled 2x and every word drawn into it turns fuzzy — while the icon
# labels, which Finder draws itself, stay sharp. A multi-representation TIFF is
# the documented way to give Finder the pixels it actually needs.
BG="$STAGE/.background/bg.png"
if [[ -f "$STAGE/.background/bg@2x.png" ]] && \
   tiffutil -cathidpicheck "$STAGE/.background/bg.png" "$STAGE/.background/bg@2x.png" \
            -out "$STAGE/.background/bg.tiff" >/dev/null 2>&1; then
  BG="$STAGE/.background/bg.tiff"
  rm -f "$STAGE/.background/bg.png" "$STAGE/.background/bg@2x.png"
  echo "  ✓ HiDPI background (retina-sharp text)"
else
  echo "  (tiffutil unavailable — shipping 1x background)"
fi
BG_NAME="$(basename "$BG")"

RW="dist/.rewisp-rw.dmg"
rm -f "$RW"
hdiutil create -volname "Rewisp" -srcfolder "$STAGE" -ov -format UDRW -fs HFS+ "$RW" >/dev/null
MP=$(hdiutil attach "$RW" -readwrite | grep -o '/Volumes/.*' | head -1)

VOL="$(basename "$MP")"          # usually "Rewisp"; macOS appends " 1" if taken
sleep 2                          # let Finder notice the new volume
# Unquoted heredoc so $VOL/$MP expand. AppleScript itself uses no $ or backticks.
osascript <<APPLESCRIPT || echo "  (Finder layout skipped)"
tell application "Finder"
  tell disk "$VOL"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set the bounds of container window to {180, 110, 900, 590}
    set opts to the icon view options of container window
    set arrangement of opts to not arranged
    set icon size of opts to 118
    set text size of opts to 13
    -- POSIX path: the "file .background:bg.png" form errors with -10006 here.
    set background picture of opts to POSIX file "$MP/.background/$BG_NAME"
    set position of item "Rewisp.app" of container window to {190, 205}
    set position of item "Applications" of container window to {530, 205}
    -- Clear the selection before saving: Finder stores it in .DS_Store, and a
    -- highlighted icon shows up as a grey box behind the app on first open.
    select {}
    update without registering applications
    delay 2
    close
  end tell
end tell
APPLESCRIPT

sync
hdiutil detach "$MP" -quiet 2>/dev/null || hdiutil detach "$MP" -force -quiet
hdiutil convert "$RW" -format UDZO -imagekey zlib-level=9 -o "$DMG" >/dev/null
rm -f "$RW"
rm -rf "$STAGE"
# Stable-named copy so the landing page can link a permanent direct-download URL
# (github.com/.../releases/latest/download/Rewisp.dmg) that never changes per version.
STABLE="dist/Rewisp.dmg"
cp -f "$DMG" "$STABLE"
echo "✓ $DMG"
echo "✓ $STABLE (stable name for the landing-page direct link)"
echo ""
echo "Ship it: gh release create v$VERSION $DMG $STABLE --title \"Rewisp $VERSION\" --notes \"...\""
echo "(upload BOTH: Rewisp.dmg keeps the landing-page download link working)"
echo "(installed apps check GitHub Releases daily and offer the update in the menu bar)"
