#!/bin/zsh
# Build a distributable Rewisp DMG: app with the daemon bundled inside,
# a one-double-click installer, and an Applications shortcut.
set -e
cd "$(dirname "$0")/.."
VERSION=$(defaults read "$(pwd)/ui/Rewisp.app/Contents/Info" CFBundleShortVersionString 2>/dev/null || echo "0.1.0")

echo "── building app ──"
(cd ui && ./build.sh)

echo "── bundling daemon into the app ──"
RES="ui/Rewisp.app/Contents/Resources/daemon"
rm -rf "$RES"
mkdir -p "$RES"
cp -R rewisp "$RES/rewisp"
find "$RES" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
cp scripts/install.sh "$RES/install.sh"
chmod +x "$RES/install.sh"
codesign --force --deep --sign - ui/Rewisp.app

echo "── staging ──"
STAGE=$(mktemp -d)
cp -R ui/Rewisp.app "$STAGE/"
ln -s /Applications "$STAGE/Applications"
cat > "$STAGE/Install Rewisp.command" <<'EOF'
#!/bin/zsh
# Double-click me after dragging Rewisp.app into Applications.
exec /Applications/Rewisp.app/Contents/Resources/daemon/install.sh
EOF
chmod +x "$STAGE/Install Rewisp.command"

DMG="dist/Rewisp-$VERSION.dmg"
mkdir -p dist
rm -f "$DMG"
hdiutil create -volname "Rewisp" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"
echo "✓ $DMG"
echo ""
echo "Ship it: gh release create v$VERSION $DMG --title \"Rewisp $VERSION\" --notes \"...\""
echo "(installed apps check GitHub Releases daily and offer the update in the menu bar)"
