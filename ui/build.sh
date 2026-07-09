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
    -framework SwiftUI -framework AppKit -framework Carbon \
    -Xlinker -weak_framework -Xlinker FoundationModels \
    -o "$APP/Contents/MacOS/Rewisp"

if [[ ! -f Rewisp.icns ]]; then
    python3 icon/make_icon.py
fi
cp Rewisp.icns "$APP/Contents/Resources/"

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
    <key>CFBundleShortVersionString</key><string>0.3.0</string>
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
    rm -rf /Applications/Rewisp.app
    cp -R "$APP" /Applications/
    open /Applications/Rewisp.app
    echo "installed + relaunched /Applications/Rewisp.app"
fi
