#!/bin/zsh
# Vendor a self-contained Python runtime into Rewisp.app.
#
# WHY: macOS ships no usable python3 (just a stub that prompts for Xcode CLT), so
# the old installer's `command -v python3` + `pip install pyobjc` step was a coin
# flip on a normal person's Mac — the #1 cause of "Could not connect to the
# server" on first run. Bundling removes the dependency entirely: the DMG has
# everything, and install.sh never touches the system Python.
#
# Uses astral-sh/python-build-standalone (relocatable CPython, the same builds uv
# ships). Run from the repo root; make_dmg.sh calls this automatically.
set -e
cd "$(dirname "$0")/.."

PY_VERSION="3.13.14"
PB_TAG="20260718"
ARCH="aarch64-apple-darwin"
APP_RES="ui/Rewisp.app/Contents/Resources"
DEST="$APP_RES/python"
CACHE=".cache/python-standalone"

# Frameworks the daemon actually imports (Quartz, Vision, Foundation, AppKit,
# ApplicationServices). Installing the full `pyobjc` meta-package would add
# ~200 MB of frameworks we never touch.
DEPS=(
  "pyobjc-framework-Quartz"
  "pyobjc-framework-Vision"
  "pyobjc-framework-Cocoa"          # Foundation + AppKit
  "pyobjc-framework-ApplicationServices"
  "numpy"
  "model2vec"
  # Encryption at rest. Self-contained wheel with SQLCipher statically linked,
  # so there is no system library to find and nothing for the user to install.
  "sqlcipher3"
)

if [[ ! -d "ui/Rewisp.app" ]]; then
  echo "✗ ui/Rewisp.app not found — run ui/build.sh first."; exit 1
fi

TARBALL="cpython-${PY_VERSION}+${PB_TAG}-${ARCH}-install_only_stripped.tar.gz"
URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PB_TAG}/${TARBALL}"

mkdir -p "$CACHE"
if [[ ! -f "$CACHE/$TARBALL" ]]; then
  echo "── downloading CPython ${PY_VERSION} (relocatable) ──"
  curl -fL "$URL" -o "$CACHE/$TARBALL"
else
  echo "✓ using cached $TARBALL"
fi

echo "── unpacking into the app bundle ──"
rm -rf "$DEST"
mkdir -p "$(dirname "$DEST")"
tar xzf "$CACHE/$TARBALL" -C "$(dirname "$DEST")"      # creates .../python

PY="$DEST/bin/python3"   # plain name for pip; daemon uses "Rewisp Backend"
[[ -x "$PY" ]] || { echo "✗ bundled python missing at $PY"; exit 1; }

echo "── installing dependencies into the bundle ──"
"$PY" -m pip install --quiet --upgrade pip
"$PY" -m pip install --quiet "${DEPS[@]}"

echo "── trimming ──"
# Nothing here needs to compile or test anything at runtime.
rm -rf "$DEST/lib/python3.13/test" "$DEST/lib/python3.13/idlelib" \
       "$DEST/lib/python3.13/tkinter" "$DEST/lib/python3.13/turtledemo" \
       "$DEST/share" 2>/dev/null || true
find "$DEST" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "$DEST" -name "*.pyc" -delete 2>/dev/null || true

# Give the interpreter a human name. macOS shows the EXECUTABLE FILENAME in the
# Screen Recording permission list, so the daemon otherwise appears as an
# anonymous "python3.13". A copy (not a symlink — TCC reports the symlink target).
# ── the helper, as a real .app ────────────────────────────────────────────────
#
# Screen Recording is granted to a code identity, and a bare mach-O is a terrible
# thing to hand TCC. Shipped as a loose binary the helper signed as
# `Identifier=-`, so macOS had nothing durable to match: the switch in System
# Settings read as ON while the running process stayed denied, extra entries piled
# up on every reinstall, and no amount of toggling fixed it.
#
# Wrapping it in a bundle with a real CFBundleIdentifier gives TCC something
# stable to record, and gives the user a properly named, icon-bearing row in the
# permission list instead of a mystery binary. PYTHONHOME (set in the launchd
# plist) points the interpreter back at the runtime, since the stdlib no longer
# sits at the usual place relative to the executable.
HELPER_APP="ui/Rewisp.app/Contents/MacOS/RewispBackend.app"
rm -rf "$HELPER_APP"
mkdir -p "$HELPER_APP/Contents/MacOS" "$HELPER_APP/Contents/Resources"
cp "$DEST/bin/python3.13" "$HELPER_APP/Contents/MacOS/Rewisp Backend"
chmod +x "$HELPER_APP/Contents/MacOS/Rewisp Backend"
[[ -f "$APP_RES/Rewisp.icns" ]] && \
    cp "$APP_RES/Rewisp.icns" "$HELPER_APP/Contents/Resources/"

cat > "$HELPER_APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Rewisp Backend</string>
  <key>CFBundleDisplayName</key><string>Rewisp Backend</string>
  <key>CFBundleExecutable</key><string>Rewisp Backend</string>
  <key>CFBundleIdentifier</key><string>com.yashmit.rewisp.backend</string>
  <key>CFBundleIconFile</key><string>Rewisp</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSUIElement</key><true/>
</dict></plist>
PLIST

# Stable identifier, and never re-signed with --deep from above (that is what
# reset it to "-" and silently revoked the grant on every rebuild).
# Nothing written into the bundle after this point, or the signature dies and
# macOS stops honouring the Screen Recording grant (Apple TN2206: adding files to
# a signed bundle always invalidates it).
find "$DEST" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "$DEST" -name "*.pyc" -delete 2>/dev/null || true
codesign --force --sign - --identifier com.yashmit.rewisp.backend "$HELPER_APP"
echo "✓ helper bundle: Contents/MacOS/RewispBackend.app (com.yashmit.rewisp.backend)"

echo "── verifying ──"
"$PY" - <<'EOF'
import Quartz, Vision, Foundation, AppKit, numpy, model2vec
from sqlcipher3 import dbapi2 as _sq
_c = _sq.connect(":memory:"); _c.execute("PRAGMA key = 'x'")
_c.execute("CREATE VIRTUAL TABLE f USING fts5(b)")   # FTS5 must survive encryption
v = Vision.VNRecognizeTextRequest.alloc().init()
assert v is not None
print("✓ Quartz / Vision / Foundation / AppKit / numpy / model2vec import")
print("✓ SQLCipher works and FTS5 survives encryption")
EOF

# ── make the runtime incapable of modifying its own bundle ─────────────────
#
# Writing anything inside a signed .app invalidates its signature, and macOS then
# refuses to honour the helper's Screen Recording grant — the switch reads ON
# while the process is denied. Python writes __pycache__ next to every module it
# imports, so by default this app destroys its own permissions minutes after
# first run.
#
# Relying on PYTHONPYCACHEPREFIX in the launchd plist was not enough: it only
# covers the daemon. ANY other process invoking this interpreter without that
# variable re-breaks the seal for everyone (observed live — a diagnostic script
# run with only PYTHONHOME set wrote 132 .pyc files and revoked the grant).
#
# Two layers instead:
#   1. sitecustomize refuses bytecode writes for every invocation of this
#      interpreter, whatever the environment.
#   2. Everything is pre-compiled and sealed in, so nothing WANTS writing.
#      (An earlier version stripped the caches, which guaranteed Python would try
#      to regenerate them on every import — precisely backwards.)
SITE="$DEST/lib/python3.13/site-packages/sitecustomize.py"
cat > "$SITE" <<'SITECUSTOMIZE'
"""Never write bytecode into the app bundle.

Rewisp's runtime lives inside Rewisp.app. Anything written in there invalidates
the bundle's code signature, and macOS responds by silently withdrawing the
helper's Screen Recording permission. The caches are pre-built and shipped, so
there is nothing to gain by writing more.
"""

import sys

sys.dont_write_bytecode = True
SITECUSTOMIZE

echo "── pre-compiling (sealed in, so nothing is written at runtime) ──"
# --invalidation-mode unchecked-hash is the load-bearing flag. By default a .pyc
# is validated against its source file's MTIME, and copying the app (Finder drag,
# cp -R, the updater) gives every .py a fresh mtime — so every cache looks stale
# and Python rewrites the lot on first import, breaking the signature before the
# user has done anything. Hash-based caches carry the source hash instead and are
# trusted without a timestamp check, so a copied bundle stays valid.
"$DEST/bin/python3" -m compileall -q -f --invalidation-mode unchecked-hash \
    "$DEST/lib/python3.13" >/dev/null 2>&1 || true

echo "✓ bundled Python: $(du -sh "$DEST" | cut -f1) at $DEST"
