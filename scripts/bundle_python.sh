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
DEST="ui/Rewisp.app/Contents/Resources/python"
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
cp "$DEST/bin/python3.13" "$DEST/bin/Rewisp Backend"
chmod +x "$DEST/bin/Rewisp Backend"

echo "── verifying ──"
"$PY" - <<'EOF'
import Quartz, Vision, Foundation, AppKit, numpy, model2vec
v = Vision.VNRecognizeTextRequest.alloc().init()
assert v is not None
print("✓ Quartz / Vision / Foundation / AppKit / numpy / model2vec all import")
EOF

echo "✓ bundled Python: $(du -sh "$DEST" | cut -f1) at $DEST"
