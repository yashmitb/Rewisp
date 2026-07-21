#!/bin/zsh
# Build Rewisp.app from the SwiftUI sources — no Xcode project needed.
set -e
cd "$(dirname "$0")"

APP=Rewisp.app
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# FoundationModels (on-device AI) is weak-linked: exists on macOS 26+,
# app still launches on 15.0 where AskEngine falls back to Claude.
swiftc -O -parse-as-library \
    -target arm64-apple-macosx15.0 \
    Sources/*.swift \
    -framework SwiftUI -framework AppKit -framework Carbon -framework LocalAuthentication \
    -Xlinker -weak_framework -Xlinker FoundationModels \
    -o "$APP/Contents/MacOS/Rewisp"

if [[ ! -f Rewisp.icns ]]; then
    python3 icon/make_icon.py
fi
cp Rewisp.icns "$APP/Contents/Resources/"
cp ../docs/MANUAL.md "$APP/Contents/Resources/MANUAL.md"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Rewisp</string>
    <key>CFBundleIconFile</key><string>Rewisp</string>
    <key>CFBundleIdentifier</key><string>com.yashmit.rewisp</string>
    <key>CFBundleExecutable</key><string>Rewisp</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>0.21.0</string>
    <key>LSMinimumSystemVersion</key><string>15.0</string>
    <key>LSUIElement</key><true/>
    <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

codesign --force --sign - "$APP"
echo "built $APP"

# Install to /Applications so Spotlight can launch it and the login item stays valid.
# REWISP_NO_INSTALL=1 builds without touching the installed copy. Release builds
# set it: make_dmg.sh should produce a DMG, not silently upgrade the machine it
# runs on (which also makes it impossible to test the in-app updater).
if [[ -n "$REWISP_NO_INSTALL" ]]; then
    echo "skipped install (REWISP_NO_INSTALL set)"
elif [[ "$1" == "--install" || -d /Applications/Rewisp.app ]]; then
    pkill -x Rewisp 2>/dev/null || true
    # Preserve the bundled runtime + daemon across a rebuild. This script only
    # rebuilds the Swift binary, but it replaces the whole bundle — which used to
    # delete Resources/python (154 MB, added by bundle_python.sh) and
    # Resources/daemon, leaving an installed app whose background helper couldn't
    # import its own modules.
    # Paths are relative to Contents/, because the helper app lives in MacOS/
    # while the runtime lives in Resources/. Leaving MacOS/RewispBackend.app out
    # of this list deleted the helper on every rebuild — the running daemon
    # survived only because its process held the deleted inode, and the next
    # restart would have killed it for good.
    KEEP=(Resources/python Resources/daemon MacOS/RewispBackend.app)
    STASH="$(mktemp -d)"
    for keep in "${KEEP[@]}"; do
        if [[ -e "/Applications/Rewisp.app/Contents/$keep" ]]; then
            mkdir -p "$STASH/$(dirname "$keep")"
            mv "/Applications/Rewisp.app/Contents/$keep" "$STASH/$keep"
        fi
    done
    rm -rf /Applications/Rewisp.app
    cp -R "$APP" /Applications/
    for keep in "${KEEP[@]}"; do
        if [[ -e "$STASH/$keep" && ! -e "/Applications/Rewisp.app/Contents/$keep" ]]; then
            mkdir -p "/Applications/Rewisp.app/Contents/$(dirname "$keep")"
            mv "$STASH/$keep" "/Applications/Rewisp.app/Contents/$keep"
        fi
    done
    rm -rf "$STASH"
    # Refresh the daemon source from the repo. Restoring the stash alone kept an
    # OLD rewisp/ alive across rebuilds: the Swift app reported the new version
    # while the Python helper beside it was stale, so daemon-side fixes silently
    # never shipped to the running helper. Costs nothing; catches everything.
    DEST="/Applications/Rewisp.app/Contents/Resources/daemon"
    if [[ -d "$DEST" ]]; then
        rm -rf "$DEST/rewisp"
        cp -R "$(dirname "$0")/../rewisp" "$DEST/rewisp"
        find "$DEST" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
        # Recompile with the same unchecked-hash mode the release build uses.
        # Those caches are trusted WITHOUT comparing against the source, so a dev
        # refresh that dropped in new .py files and left stale .pyc behind would
        # silently keep running the old code. Cheap insurance against a very
        # confusing afternoon.
        PY313="/Applications/Rewisp.app/Contents/Resources/python/bin/python3"
        [[ -x "$PY313" ]] && "$PY313" -m compileall -q -f \
            --invalidation-mode unchecked-hash "$DEST/rewisp" >/dev/null 2>&1 || true
        # Never --deep here: it re-signs Resources/python/bin/"Rewisp Backend"
        # and resets its identifier to "-", silently revoking the user's Screen
        # Recording grant on every rebuild.
        codesign --force --sign - /Applications/Rewisp.app 2>/dev/null || true
    fi
    open /Applications/Rewisp.app
    echo "installed + relaunched /Applications/Rewisp.app"
fi
