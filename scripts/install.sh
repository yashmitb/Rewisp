#!/bin/zsh
# Rewisp installer — sets up the background capture daemon + nightly digest for
# the current user. Idempotent; safe to re-run. Works for both a source checkout
# and a copy of Rewisp.app with the daemon bundled in Resources/daemon.
set -e

echo "── Rewisp installer ──"

# 1. Locate the daemon source (repo checkout, or bundled inside the app).
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -d "$SCRIPT_DIR/../rewisp" ]]; then
    DAEMON_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"          # source checkout
elif [[ -d "/Applications/Rewisp.app/Contents/Resources/daemon/rewisp" ]]; then
    DAEMON_DIR="/Applications/Rewisp.app/Contents/Resources/daemon"
else
    echo "✗ Can't find the rewisp daemon package."; exit 1
fi
echo "✓ daemon source: $DAEMON_DIR"

# 2. Python 3.11+ with pyobjc.
PY="$(command -v python3 || true)"
[[ -z "$PY" ]] && { echo "✗ python3 not found. Install from python.org, then re-run."; exit 1; }
"$PY" - <<'EOF' || "$PY" -m pip install --quiet pyobjc
import Quartz, Vision  # noqa
EOF
echo "✓ python3 + pyobjc: $PY"

# 2b. model2vec — local semantic-search embeddings (pure numpy, no torch).
# Optional: if it can't install, Rewisp falls back to keyword-only search.
"$PY" - <<'EOF' || "$PY" -m pip install --quiet model2vec
import model2vec  # noqa
EOF
echo "✓ semantic search (model2vec) ready"

# 3. Rewisp.app in /Applications (skipped when already there or building from source).
if [[ ! -d /Applications/Rewisp.app && -d "$SCRIPT_DIR/../ui/Rewisp.app" ]]; then
    cp -R "$SCRIPT_DIR/../ui/Rewisp.app" /Applications/
    echo "✓ installed /Applications/Rewisp.app"
fi

# 4. launchd agents: capture daemon (always on) + digest (9 PM daily).
AGENTS="$HOME/Library/LaunchAgents"
mkdir -p "$AGENTS"

cat > "$AGENTS/com.rewisp.daemon.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
    <key>Label</key><string>com.rewisp.daemon</string>
    <key>ProgramArguments</key><array>
        <string>$PY</string><string>-m</string><string>rewisp</string><string>daemon</string>
    </array>
    <key>WorkingDirectory</key><string>$DAEMON_DIR</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardErrorPath</key><string>/tmp/rewisp-daemon.err</string>
</dict></plist>
PLIST

cat > "$AGENTS/com.rewisp.digest.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
    <key>Label</key><string>com.rewisp.digest</string>
    <key>ProgramArguments</key><array>
        <string>$PY</string><string>-m</string><string>rewisp</string><string>digest</string>
    </array>
    <key>WorkingDirectory</key><string>$DAEMON_DIR</string>
    <key>EnvironmentVariables</key><dict>
        <key>PATH</key><string>/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin</string>
    </dict>
    <key>StartCalendarInterval</key><dict>
        <key>Hour</key><integer>21</integer><key>Minute</key><integer>0</integer>
    </dict>
</dict></plist>
PLIST

UID_N=$(id -u)
launchctl bootout "gui/$UID_N/com.rewisp.daemon" 2>/dev/null || true
launchctl bootout "gui/$UID_N/com.rewisp.digest" 2>/dev/null || true
launchctl bootstrap "gui/$UID_N" "$AGENTS/com.rewisp.daemon.plist"
launchctl bootstrap "gui/$UID_N" "$AGENTS/com.rewisp.digest.plist"
echo "✓ launchd agents loaded (daemon + 9 PM digest)"

# 5. Launch the menu bar app.
open /Applications/Rewisp.app 2>/dev/null || true

echo ""
echo "Done. Rewisp will ask for Screen Recording permission —"
echo "grant it to the app named “Python” in System Settings."
echo "Optional: install Claude Code and run \`claude\` once for the nightly Digest."
