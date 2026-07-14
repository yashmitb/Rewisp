---
name: updateandpush
description: Full Rewisp release procedure — bump the version, sync every doc/README/manual, refresh the landing page + in-app info with the latest features, build the DMG, commit, push, and cut a GitHub release. Use when the user says "updateandpush", "cut a release", "ship a new version", or "update all the docs and release".
---

# updateandpush — Rewisp release + docs + landing + manual

One command to take the current `main` and ship it: version bump, every doc and
the in-app manual synced to what actually shipped, landing page refreshed, DMG
built, release cut. Follow the steps in order. Confirm the version and release
notes with the user before the irreversible `gh release create`.

## 0. Preflight
- `git status` clean and on `main` (commit/stash anything loose first).
- `python3 -m pytest tests/ -q` green. If red, STOP and fix before releasing.
- `git fetch && git log --oneline $(git describe --tags --abbrev=0)..HEAD` — this
  diff since the last tag is your changelog source for notes + doc updates.

## 1. Decide the version
- Current version = `CFBundleShortVersionString` in `ui/build.sh`.
- Bump: **patch** (x.y.Z) for fixes only, **minor** (x.Y.0) for new features,
  **major** for big/breaking. New user-facing features → minor at least.
- Ask the user to confirm the target version if `$ARGUMENTS` didn't give one.

## 2. Bump the version everywhere
- `ui/build.sh` → `CFBundleShortVersionString` = new version (source of truth).
- `rewisp/__init__.py` → `__version__` = same (keep in sync).
- Grep for any other hard-coded version: `grep -rn "<oldversion>" rewisp ui site docs README.md`.

## 3. Update the docs (`docs/` + README)
Read each, then edit to match what shipped (use the changelog diff from step 0):
- `docs/PROGRESS.md` — bump the "Current status" line; add a dated entry to the
  "Post-v0.1 releases" log for this version. Never delete history.
- `docs/BRIEF.md` — update "Current version" + the feature set / status sections.
- `docs/MANUAL.md` — add how-to for every new user-facing feature (how to trigger
  it, what it does, any settings). This is the user's guide — be concrete.
- `README.md` — feature list + version if referenced.
- `docs/SECURITY.md` — only if the release touched capture/privacy/credentials.

## 4. Update the in-app info
- `ui/Sources/HelpTab.swift` — the built-in manual. Mirror the new `docs/MANUAL.md`
  sections so the in-app help matches. (Version there reads from the bundle
  automatically — no edit needed.)
- `ui/Sources/Onboarding.swift` — add new features to the onboarding feature list
  / demos if they belong there.
- `ui/Sources/MainWindow.swift` — Settings sections: add toggles/descriptions for
  any new user-facing setting shipped this version.

## 5. Update the landing page (`site/`)
- `site/index.html` — add/refresh feature cards + the "Watch it work" demos for
  new features; keep copy accurate (on-device optional, cloud by choice, no API
  key). Update any version pill.
- `site/css/styles.css`, `site/js/demos.js` — new demo animations if a feature
  warrants one (follow the existing scroll-triggered pattern).
- **Bump the cache-bust query** on the CSS/JS links in `index.html`
  (`styles.css?v=YYYYMMDDx` → new value) so the GitHub Pages CDN serves fresh
  assets immediately instead of a ~10-min-stale copy.
- If screenshots are stale, recapture from the live app (see step 6 build first),
  save to `site/assets/`.

## 6. Build + verify the app
- `cd ui && ./build.sh` — must show `installed` with no `error:` lines.
- Restart the daemon so it runs the shipped code:
  `launchctl kickstart -k gui/$(id -u)/com.rewisp.daemon` and confirm
  `curl -s http://127.0.0.1:43117/status -H "X-Rewisp-Token: $(cat ~/Rewisp/.api_token)"`
  returns `capture_state: active` with no traceback in `~/Rewisp/daemon.log`.

## 7. Build the DMG
- `./scripts/make_dmg.sh` — produces `dist/Rewisp-<version>.dmg` AND the stable
  `dist/Rewisp.dmg`. Both are needed (the stable name keeps the landing-page
  `releases/latest/download/Rewisp.dmg` link working).

## 8. Commit + push
- Stage everything: docs, site, ui, rewisp, scripts, dist.
- Commit (user-only authorship — NEVER add a Claude co-author; use the user's
  GitHub noreply email). Message: `release: vX.Y.Z — <one-line theme>` plus a
  short bullet body of the headline changes.
- `git push`.
- Wait for the Pages deploy: `gh run list --workflow=pages.yml -L1` shows
  `completed success`. The landing page updates via that workflow.

## 9. Cut the GitHub release (irreversible — confirm first)
- Draft release notes from the changelog diff: group by feature, plain language,
  lead with what the user gets. Confirm the notes + version with the user.
- Upload BOTH assets:
  ```
  gh release create vX.Y.Z dist/Rewisp-X.Y.Z.dmg dist/Rewisp.dmg \
    --title "Rewisp X.Y.Z — <theme>" --notes "<notes>"
  ```
  Uploading `Rewisp.dmg` (stable name) is what keeps the landing-page direct link
  and every installed app's auto-updater working — do not skip it.

## 10. Verify the release
- `gh release view vX.Y.Z --json assets --jq '.assets[].name'` shows both
  `Rewisp-X.Y.Z.dmg` and `Rewisp.dmg`.
- `curl -sI https://github.com/yashmitb/Rewisp/releases/latest/download/Rewisp.dmg`
  → 302 to the new version's asset.
- Landing page live at https://yashmitb.github.io/Rewisp/ shows the new features.

## Guardrails
- Commits are user-only; never `Co-Authored-By: Claude`.
- Never bill an API key; nothing here should call a paid engine.
- `gh release create` is the point of no return — confirm version + notes before it.
- If tests are red or the build errors, STOP and fix; do not release broken code.
