#!/bin/zsh
# Remove Rewisp completely.
#
#   ./uninstall.sh              keep my memories (~/Rewisp)
#   ./uninstall.sh --all        delete my memories too
#
# Rewisp 0.16+ can uninstall itself from Settings -> Your data -> Uninstall.
# This script is for older versions, or for cleaning up a machine where the app
# is already gone but its background pieces are not.
#
# Safe to run twice; every step is a no-op if that piece is already missing.
set -u

ALL=0
[[ "${1:-}" == "--all" ]] && ALL=1

UID_N=$(id -u)
APP="/Applications/Rewisp.app"
DATA="$HOME/Rewisp"
AGENTS="$HOME/Library/LaunchAgents"

echo "── stopping the background helper ──"
# FIRST, always. The daemon runs with KeepAlive, so removing its binary while the
# job is still loaded makes launchd respawn it in a loop against a missing file.
for label in com.rewisp.daemon com.rewisp.digest; do
    launchctl bootout "gui/$UID_N/$label" 2>/dev/null && echo "  stopped $label"
done
pkill -f "Rewisp Backend" 2>/dev/null
pkill -x Rewisp 2>/dev/null
sleep 1

echo "── removing startup items ──"
for label in com.rewisp.daemon com.rewisp.digest; do
    if [[ -f "$AGENTS/$label.plist" ]]; then
        rm -f "$AGENTS/$label.plist" && echo "  removed $label.plist"
    fi
done

echo "── releasing permissions ──"
# BEFORE deleting the app: tccutil resolves a bundle identifier by looking the
# app up on disk. Once the bundle is gone it fails with "No such bundle
# identifier" (-10814) and the Screen Recording rows are stranded in System
# Settings with no way to clear them except finding the row and clicking minus.
for id in com.yashmit.rewisp.backend com.yashmit.rewisp; do
    tccutil reset ScreenCapture "$id" >/dev/null 2>&1 && echo "  released ScreenCapture ($id)"
    tccutil reset Accessibility "$id" >/dev/null 2>&1
done

echo "── removing preferences ──"
defaults delete com.yashmit.rewisp 2>/dev/null && echo "  removed preferences"
rm -f "$HOME/Library/Preferences/com.yashmit.rewisp.plist"
killall -u "$USER" cfprefsd 2>/dev/null   # drop the cached copy

echo "── removing the app ──"
if [[ -d "$APP" ]]; then
    rm -rf "$APP" && echo "  removed $APP"
else
    echo "  (not installed)"
fi
# Older versions ran on the system Python and left these behind.
rm -f /tmp/com.rewisp.*.err /tmp/com.rewisp.*.out 2>/dev/null

if (( ALL )); then
    echo "── removing your memories ──"
    if [[ -d "$DATA" ]]; then
        SIZE=$(du -sh "$DATA" 2>/dev/null | cut -f1)
        rm -rf "$DATA" && echo "  removed $DATA ($SIZE)"
    else
        echo "  (nothing there)"
    fi
else
    if [[ -d "$DATA" ]]; then
        echo "── keeping your memories ──"
        echo "  $DATA ($(du -sh "$DATA" 2>/dev/null | cut -f1)) left alone."
        echo "  Delete it yourself, or re-run with --all."
    fi
fi

echo ""
echo "✓ Rewisp removed."
LEFT=$(launchctl list 2>/dev/null | grep -c rewisp)
if (( LEFT > 0 )); then
    echo "! $LEFT launchd job(s) still listed — log out and back in to clear them."
fi
echo "  If 'Rewisp Backend' still appears in System Settings > Privacy & Security >"
echo "  Screen & System Audio Recording, select it and click the minus button."
