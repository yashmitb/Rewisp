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
    <key>CFBundleShortVersionString</key><string>0.15.1</string>
    <key>LSMinimumSystemVersion</key><string>15.0</string>
    <key>LSUIElement</key><true/>
    <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

codesign --force --sign - "$APP"
echo "built $APP"

# Install to /Applications so Spotlight can launch it and the login item stays valid.
if [[ "$1" == "--install" || -d /Applications/Rewisp.app ]]; then
    pkill -x Rewisp 2>/dev/null || true
    # Preserve the bundled runtime + daemon across a rebuild. This script only
    # rebuilds the Swift binary, but it replaces the whole bundle — which used to
    # delete Resources/python (154 MB, added by bundle_python.sh) and
    # Resources/daemon, leaving an installed app whose background helper couldn't
    # import its own modules.
    STASH="$(mktemp -d)"
    for keep in python daemon; do
        [[ -d "/Applications/Rewisp.app/Contents/Resources/$keep" ]] && \
            mv "/Applications/Rewisp.app/Contents/Resources/$keep" "$STASH/$keep"
    done
    rm -rf /Applications/Rewisp.app
    cp -R "$APP" /Applications/
    for keep in python daemon; do
        [[ -d "$STASH/$keep" && ! -d "/Applications/Rewisp.app/Contents/Resources/$keep" ]] && \
            mv "$STASH/$keep" "/Applications/Rewisp.app/Contents/Resources/$keep"
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
        # Never --deep here: it re-signs Resources/python/bin/"Rewisp Backend"
        # and resets its identifier to "-", silently revoking the user's Screen
        # Recording grant on every rebuild.
        codesign --force --sign - /Applications/Rewisp.app 2>/dev/null || true
    fi
    open /Applications/Rewisp.app
    echo "installed + relaunched /Applications/Rewisp.app"
fi
