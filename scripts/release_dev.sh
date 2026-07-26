#!/bin/zsh
# Cut a DEVELOPER (pre-release) build — only testers on the dev channel see it.
#
#   scripts/release_dev.sh 0.28.0-dev.1 ["release notes"]
#
# Stable users are untouched: GitHub's /releases/latest (what the stable channel
# and the landing-page download link resolve to) excludes prereleases. The dev
# channel (Settings → Help → Developer updates) reads /releases, so a tester on
# an older build is offered this one, and rolls onto the plain 0.28.0 stable
# automatically once it ships (a release outranks every -dev.N by semver).
#
# When verified, ship the public build the normal way (updateandpush → a NON-
# prerelease v0.28.0), which becomes /releases/latest for everyone.
set -e
cd "$(dirname "$0")/.."

VER="$1"
NOTES="${2:-Developer preview — a testing build, not yet public. Expect rough edges.}"

if [[ -z "$VER" ]]; then
  echo "usage: scripts/release_dev.sh <version-dev.N> [notes]   e.g. 0.28.0-dev.1"; exit 1
fi
if [[ "$VER" != *-dev.* ]]; then
  echo "✗ a dev version must contain -dev.N (got '$VER') — that suffix is what keeps"
  echo "  it a prerelease and orders it below the stable build it precedes."; exit 1
fi
if git rev-parse "v$VER" >/dev/null 2>&1; then
  echo "✗ tag v$VER already exists — bump the -dev.N number."; exit 1
fi

echo "── tests ──"
python3 -m pytest tests/ -q || { echo "✗ tests red — not cutting a dev build"; exit 1; }

echo "── building DMG at version $VER ──"
REWISP_VERSION="$VER" ./scripts/make_dmg.sh >/dev/null

DMG="dist/Rewisp-$VER.dmg"
[[ -f "$DMG" ]] || { echo "✗ expected $DMG, not found"; exit 1; }

echo "── cutting prerelease v$VER ──"
# Only the versioned DMG — never dist/Rewisp.dmg, which is the stable channel's
# fixed-name anchor and the landing-page link.
gh release create "v$VER" "$DMG" \
  --prerelease \
  --title "Rewisp $VER (beta)" \
  --notes "$NOTES"

echo "✓ dev release v$VER is live as a prerelease."
echo "  Stable users are unaffected. Testers with Developer updates ON will see it."
