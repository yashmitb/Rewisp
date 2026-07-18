#!/bin/zsh
# Rewisp quality gate — everything must pass before code ships.
# Run manually (`./scripts/check.sh`) or automatically via the pre-push hook
# (`./scripts/check.sh --install-hook` once). Fast mode for hooks: SKIP_BUILD=1
# skips the Swift build (pushes that don't touch ui/ set this automatically).
set -e
cd "$(dirname "$0")/.."
PY=/Library/Frameworks/Python.framework/Versions/3.13/bin/python3
[ -x "$PY" ] || PY=python3

if [[ "$1" == "--install-hook" ]]; then
    mkdir -p .git/hooks
    cat > .git/hooks/pre-push <<'HOOK'
#!/bin/zsh
# Skip the slow Swift build when the push doesn't touch Swift/UI sources.
if git diff --name-only @{push}..HEAD 2>/dev/null | grep -q "^ui/"; then
    exec ./scripts/check.sh
else
    SKIP_BUILD=1 exec ./scripts/check.sh
fi
HOOK
    chmod +x .git/hooks/pre-push
    echo "✓ pre-push hook installed — every push now runs the quality gate"
    exit 0
fi

fail() { echo "✗ QUALITY GATE FAILED: $1"; exit 1 }

echo "── 1/4 python tests ──"
"$PY" -m pytest tests/ -q || fail "pytest"

echo "── 2/4 every module imports ──"
"$PY" - <<'EOF' || fail "imports"
import importlib, pathlib
for f in sorted(pathlib.Path("rewisp").glob("*.py")):
    if f.stem.startswith("__"):
        continue
    importlib.import_module(f"rewisp.{f.stem}")
print(f"ok — all modules import")
EOF

echo "── 3/4 swift build ──"
if [[ -n "$SKIP_BUILD" ]]; then
    echo "skipped (no ui/ changes)"
else
    (cd ui && ./build.sh --no-install 2>/dev/null || ./build.sh) | grep -q "built" || fail "swift build"
    echo "ok — Rewisp.app builds"
fi

echo "── 4/4 daemon API smoke (if running) ──"
TOK=$(cat ~/Rewisp/.api_token 2>/dev/null || true)
if [[ -n "$TOK" ]] && curl -s -m 3 http://127.0.0.1:43117/status -H "X-Rewisp-Token: $TOK" | grep -q "capture_state"; then
    for ep in promises series precog nudges memory-layers; do
        curl -s -m 3 "http://127.0.0.1:43117/$ep" -H "X-Rewisp-Token: $TOK" | grep -qv '"error"' \
            || fail "endpoint /$ep"
    done
    echo "ok — live endpoints healthy"
else
    echo "skipped (daemon not running)"
fi

echo "✓ QUALITY GATE PASSED"
