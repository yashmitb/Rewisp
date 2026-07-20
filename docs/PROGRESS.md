# Rewisp — Build Progress

**Current status (v0.17.0, 2026-07-20):** Phases 0–5 shipped, plus the "intelligent memory" cycle, the Forgetting Model, the MCP connector, and — as of v0.12 — a genuinely installable app. In daily use (~180+ wisps/day, 11,000+ wisps). 147 tests. 28 releases (v0.1.0 → v0.17.0).
**Next up:** Personas (auto-select the autofill profile from app/site context — researched, in `todo.md`). Also queued: the capture-loop autorelease leak, a LICENSE file, an uninstaller, and auth on the MCP server.

> The v1 build plan (Phases 0–5) is preserved below as the permanent timeline.
> Everything shipped after v0.1.0 is logged in the "Post-v0.1 releases" section
> at the bottom.

---

## Phase 0 — Dia browser test (MANDATORY FIRST)

- [x] Test Chrome-style AppleScript URL query on Dia (2026-07-08)
- [x] Test Chrome-style AppleScript title query on Dia (2026-07-08)
- [x] Test frontmost window title fallback (2026-07-08)
- [x] Check Dia-specific scripting dictionary (2026-07-08)
- [x] Record results in Blockers section (2026-07-08)
- [x] Decision gate: AppleScript works → Capture uses it for URL trigger (2026-07-08)

## Phase 1 — Capture + Store

- [x] Daemon skeleton (Python, pyobjc, 0.5s polling loop) (2026-07-08)
- [x] Window-switch trigger — via window server, NOT NSWorkspace (see Blockers) (2026-07-08)
- [x] Screenshot of display containing frontmost window (2026-07-08)
- [x] Vision framework OCR (local, verified on real screen) (2026-07-08)
- [x] OCR reading-order reassembly — boxes grouped into visual rows, sorted top→bottom, left→right (dense multi-column pages were scrambled) (2026-07-08)
- [x] OCR max-recall pass (2026-07-09): Vision revision 3 + auto language;
      MAX_OCR_CHARS 10k→25k (dense pages were truncated); tiled second pass —
      2x2 overlapping quadrants at full res catch small text the whole-frame
      pass under-resolves, merged with spatial + seam-fragment dedupe.
      Measured on a real 3024x1964 frame: 1,985 → 3,294 chars (+39 whole
      boxes recovered: file-tree items, code lines, tab titles), 1.3s/capture.
- [x] SQLite store with FTS5 (WAL mode, triggers keep FTS synced) (2026-07-08)
- [x] Image never touches disk — CGImage OCR'd in memory, released (2026-07-08)
- [x] URL trigger via Dia AppleScript (2026-07-08)
- [x] Scroll-settle trigger (~2s) (2026-07-08)
- [x] Heartbeat trigger — every 60s with no other trigger, dedupe drops unchanged screens (2026-07-08)
- [ ] Idle guard (5 min no input → pause) — coded, not yet observed live
- [x] Dedupe layer (thumbnail diff, <5% change → discard) — unit-verified (2026-07-08)
- [x] Kill list enforcement — Messages frontmost → "capture paused" logged, 0 rows in DB (2026-07-08)
- [x] Kill list hot-reload — Settings edits apply within ~2s, no restart (2026-07-08)
- [x] Pause via CLI + global hotkey Cmd+Option+P + menu bar (2026-07-08)
- [x] Permission detection (Screen Recording + Accessibility) with setup guide (2026-07-08)
- [x] SUCCESS TEST: 354 captures in one day; known pages found via FTS (2026-07-08)

## Phase 2 — Ask

- [x] CLI `python3 -m rewisp ask "..."` (2026-07-08)
- [x] Local time-phrase parsing (today/yesterday/weekdays/N days ago/dayparts/weeks) (2026-07-08)
- [x] FTS search over captures + summaries (2026-07-08)
- [x] Retrieval quality pass (2026-07-08):
      most-recent captures always included verbatim ("what's on my screen" questions);
      FTS-miss falls back to recent captures in the asked time window;
      snippets 24→48 tokens. Verified: "what do i have due on july 12th" →
      "HOMEWORK Quiz 3.2 is due July 12 at 11:59pm" (previously random answers).
- [x] Claude call via Claude Code (refuses to run if ANTHROPIC_API_KEY set) (2026-07-08)
- [x] Apple on-device Foundation Model for quick answers (2026-07-08):
      daemon builds compact prompt (/context), Swift runs it on-device (~6s),
      Claude fallback when unavailable / errored / "not found". Model badge in UI.
- [x] Structured answers (ANSWER/DETAIL/SOURCE/TIME/COPY), parsed both sides (2026-07-08)
- [x] Save exchange to chats table (both engines) (2026-07-08)
- [ ] SUCCESS TEST: correctly answers 5 real questions about last 2 days (needs 2 days of data)

## Phase 3 — Digest + Memory + Vault

- [x] launchd job at 9 PM local — com.rewisp.digest loaded (2026-07-08)
- [x] Wake catch-up + once/day guard (2026-07-08)
- [x] Local input compression (line dedupe, group by hour+app, 60k char cap) (2026-07-08)
- [x] One Claude call → summary, threads, subtext, memory proposals — first live
      digest ran 2026-07-08 (5 memory proposals; 9 PM launchd fired but hit the
      Claude session limit; completed after 11:30 PM reset). Fixed the real bug:
      daemon catch-up used time.monotonic(), which PAUSES during Mac sleep, so
      the 15-min retry throttle stretched to hours — now wall-clock. (2026-07-09)
- [x] Write summaries.summary_md + threads_md — verified, shown in Today tab (2026-07-09)
- [x] Memory file Pending/Confirmed flow + UI review tab (2026-07-08)
- [x] Vault ingest (.md .txt .docx .pdf) + FTS index + credential refusal (2026-07-08)
- [x] Vault UI: drag-drop in, delete, add note — main window Vault tab (2026-07-08)
- [x] Retention job (2026-07-08)
- [x] Digest call counter + size logging (2026-07-08)
- [ ] SUCCESS TEST: Digest ran automatically, readable recap + threads (tonight 9 PM)

## Phase 4 — UI (native SwiftUI, talks to daemon over localhost:43117)

- [x] Localhost HTTP API — now token-gated (X-Rewisp-Token, ~/Rewisp/.api_token 0600) (2026-07-08)
- [x] SwiftUI menu bar app, mini dashboard popover (2026-07-08)
- [x] Menu bar icon state: filled=capturing, pause badge=paused, hand=kill-list, hollow=daemon down; polls /status every 5s (2026-07-08)
- [x] Esc closes the popover; Esc in search panel clears-then-closes (2026-07-08)
- [x] Global hotkey Cmd+Shift+Space search panel (2026-07-08)
- [x] Panel EXPAND FIX (2026-07-08): NSHostingView proposes the small window height,
      so a flexible ScrollView collapsed to ~0 and the window never grew (chicken-egg).
      Answer content is now measured INSIDE the ScrollView and the ScrollView gets an
      explicit height. AUTO-VERIFIED: 56 → 97 (searching) → 185px (answer) via test hook.
- [x] Test hook: distributed notification "com.rewisp.test.ask" drives the panel
      (synthetic keystrokes can't reach a nonactivating panel) (2026-07-08)
- [x] Main window: Chat (history + input), Vault (drag-drop/delete/note), Memory
      (approve/delete), Settings (kill list editor, engine info, data, shortcuts) (2026-07-08)
- [x] Model badge on answers (Apple on-device / Claude) (2026-07-08)
- [x] Copy button copies just the answer value (2026-07-08)
- [x] App icon, /Applications install, login item, launchd daemon (2026-07-08)
- [x] SUCCESS TEST: hotkey panel answered "what is my name" correctly via on-device model, screenshot-verified (2026-07-08)

## Phase 5 — Distribution + Polish

- [x] Onboarding flow (first launch): welcome → privacy → permissions with live
      status checks + Open Settings buttons → tutorial. Screenshot-verified. (2026-07-08)
- [x] GitHub repo: public https://github.com/yashmitb/Rewisp, sole collaborator
      yashmitb, README written (2026-07-08)
- [x] Auto-update: app checks GitHub Releases daily, "Get update" banner in the
      popover downloads the new DMG. v0.1.0 released with DMG asset. (2026-07-08)
- [x] DMG packaging: scripts/make_dmg.sh bundles the daemon inside the app +
      "Install Rewisp.command" (launchd setup, pyobjc check). dist/Rewisp-0.1.0.dmg built. (2026-07-08)
- [x] Landing page live at https://yashmitb.github.io/Rewisp/ (site/, GitHub
      Pages via Actions, typed-demo hero, privacy + how-it-works sections) (2026-07-08)
- [x] Export everything: `rewisp export` / Settings button → ~/Rewisp/export/
      (summaries.md, chats.md, captures.csv, memory.md). Verified: 577 captures,
      62 chat lines exported human-readable. (2026-07-09)
- [x] Weekly time report: /report endpoint + `rewisp report` CLI + "This week"
      card in the Today tab (stored digests + live compute) (2026-07-09)
- [x] Daily local backup of summaries + memory (daemon daily tick, keeps 14) (2026-07-09)
- [x] Notification setting: Silent / digest-ready ping (Settings → Notifications) (2026-07-09)
- [x] Main window redesign: custom sidebar (wordmark, matchedGeometry selection,
      live capture pill), Today tab (greeting, digest card, loose threads, weekly
      bars), chat bubbles + suggestion chips, styled vault/memory/settings cards (2026-07-09)
- [x] Engine fallback chain (2026-07-09): auto = Claude Pro → ChatGPT Plus
      (Codex CLI, subscription only — refuses OPENAI_API_KEY) → free local
      Ollama (unlimited, weaker; warned in UI). Settings picker shows install
      state per engine; answers badge which engine replied.
- [x] Digest controls (2026-07-09): run hour + frequency (daily/2/3/weekly)
      settings honored by scheduler; "Run digest now" button with
      "not needed" warning, runs in a worker thread with live status.
- [x] Esc closes the menu bar popover — local keyDown monitor; SwiftUI's
      onExitCommand never fired there (field editor eats cancelOperation) (2026-07-09)
- [x] Animation pass on popover + search panel: overshoot-settle entrance,
      pulsing sparkles while searching, offset+fade content transitions (2026-07-09)
- [x] Landing page: wisp SVG favicon + stroke-icon cards (emojis out) (2026-07-09)
- [x] Multi-browser support (2026-07-09): Chromium family (Chrome, Arc, Edge,
      Brave, Vivaldi, Opera, Dia) + Safari get URL trigger + URL kill list;
      Chromium incognito detected via window `mode` (capture fully pauses) —
      live-verified on Chrome (normal vs incognito) and Safari. Firefox
      title-only. Was Dia-only: silent kill-list gap for DMG users.
- [x] Form detector (2026-07-09): daemon /form-context reads the focused text
      field over AX (panel is non-activating, so the field keeps focus);
      panel shows "You were in a '<label>' field — Find mine" which asks the
      Vault and offers Copy. Copy-assist only; Rewisp never fills or submits.
- [x] Performance: tick's two window-list queries merged into one
      (frontmost_info) (2026-07-09)
- [ ] SUCCESS TESTS (definition of done): <5% CPU, <300 MB RAM all day; kill list zero rows; memory learned 1 fact; export human-readable ✓; $0 beyond Pro

---

## Blockers / open questions

### Dia AppleScript test — RESOLVED (2026-07-08)

Dia (Chromium-based) fully supports Chrome-style AppleScript (`URL of active tab of front window`). Cannot hold `active tab` in a variable (error -1700) — query properties directly. System Events window names are truncated; query Dia directly.

### Gotchas discovered (2026-07-08)

1. **Dia AppleScript:** no `active tab` variables (error -1700); no incognito property (title-keyword heuristic instead).
2. **NSWorkspace.frontmostApplication() caches forever** without a runloop — use `CGWindowListCopyWindowInfo` layer-0 owner.
3. **pyobjc CGBitmapContextGetData** returns `objc.varlist` — use `.as_buffer(size)`.
4. **NSHostingView height proposal chicken-egg** (the panel expand bug): the hosting view proposes the current window size to SwiftUI, so flexible views (ScrollView) collapse instead of reporting their natural size. Measure content inside the scroll view, set explicit frame heights, then let the window follow the outer geometry. Never animate the window frame and SwiftUI content simultaneously.
5. **Synthetic keystrokes (CGEventPostToPid) don't reach a nonactivating NSPanel** — UI tests drive a distributed-notification hook instead.
6. **Apple on-device model rambles** past its first answer (invents follow-up Q&As) — parser stops at the first repeated field; temperature 0.1, 250-token cap.
7. **launchd daemon permission identity** is "Python" (Python.app inside the framework), not Terminal/VS Code.
8. **Accessibility calls segfault Chromium** even on the main thread — form detection must run in a crash-isolated `rewisp axhelper` subprocess; the daemon talks to it over stdin/stdout and never touches AX itself. Chromium only exposes its web-AX tree while the enabling client stays alive, so the long-lived daemon holds it open.
9. **Non-activating panel + `NSApp.activate`** = the click-twice bug. Activating the app stole app-level focus, so dismissing the panel left Rewisp active and the next click just re-activated the app behind it. A `.nonactivatingPanel` takes key focus for typing without activating — don't call `NSApp.activate`.
10. **GitHub Pages CDN caches assets ~10 min** — a browser cache-reset refetches from the edge, not origin, so a fixed CSS/JS still looked broken. Version the asset URLs (`styles.css?v=…`) to force a fresh fetch.

---

## Launch — Product Hunt, 2026-07-20

**#5 product of the day, 187 upvotes.** First release into the world beyond one
Mac.

What it actually produced, in order of usefulness:

- **A real bug report from a stranger** — a custom API failing with
  `403: error code: 1010`, which turned out to be Cloudflare rejecting our
  missing `User-Agent`. Fixed in v0.16.4. Worth more than the ranking.
- **The first outside PR** ([#1](https://github.com/yashmitb/Rewisp/pull/1)),
  fixing two bugs I'd shipped: the `PYTHONHOME` leak into child virtualenvs, and
  Codex detection failing under a GUI LaunchAgent's minimal `PATH`. Shipped as
  v0.17.0.
- **Questions that forced honesty.** Where the boundary of "reads your screen"
  sits (spoken words are invisible), whether the database is encrypted at rest
  (it isn't — FileVault and file permissions are the protection), and how six
  months of screen text stays searchable in one SQLite file. The README now has
  an "honest about the boundaries" section because of these.
- **135 downloads** in the first two days, two clear spikes.
- Five vendor emails, none of which mentioned anything not already on the
  landing page. Worth ignoring as a class.

## v0.17.0 — first outside contribution (2026-07-20)

[#1](https://github.com/yashmitb/Rewisp/pull/1) from **@yannisxu**, fixing two
real bugs. Merged as submitted.

- **The bundled runtime broke local-model setup.** v0.12 put `PYTHONHOME` in the
  launchd plist so the packaged daemon could find its own stdlib. Child processes
  inherit it, so the MLX virtualenv resolved imports against Rewisp's runtime
  instead of its own and died at `import encodings` — leaving a directory with a
  `python` symlink that could not import anything, which `ensure_mlx` then
  retried `pip` inside forever. Child environments are now sanitised, a broken
  venv is rebuilt rather than retried, and `_base_python()` resolves the real
  interpreter instead of `sys.executable` (which under our bundle is the nested
  `RewispBackend` helper).
- **ChatGPT Plus users were told they had no ChatGPT.** GUI LaunchAgents run with
  a minimal `PATH`, so `shutil.which("codex")` failed even with ChatGPT installed
  and signed in. A single `cli_path()` now checks GUI-safe fallbacks including
  the Codex binary inside `ChatGPT.app`, and — the subtler half — detection,
  invocation and benchmarks all use it, so the UI can no longer claim an engine
  is available while the call fails.
- **Injection closed:** the Hugging Face repo name was interpolated into a Python
  string passed to `-c`. It is now `sys.argv[1]`.
- 4 new tests covering both failure modes. 143 → 147.

## v0.16.4 — custom APIs blocked by Cloudflare (2026-07-20)

First bug report from someone who isn't me. A user's custom API returned
`403: error code: 1010` against several different models.

1010 is a **Cloudflare** code, not the provider's: "banned based on your
browser's signature". Rewisp sent no `User-Agent`, so urllib supplied
`Python-urllib/3.13`, which plenty of providers behind Cloudflare reject
outright. The request never reached the provider, which is why changing models
made no difference and why it looked like an auth problem.

- Every outbound call now identifies itself as
  `Rewisp/<version> (macOS; +github url)` — five call sites, since Gemini, the
  local model and Ollama had the same blind spot.
- 403/1010, 401 and 404 now produce specific guidance instead of a raw status
  dump: the 404 case in particular tells people their base URL needs to end in
  `/v1`, which is the other common way this is misconfigured.
- Also this release: the repo finally has a `LICENSE`. The README had claimed MIT
  since the first commit while the absent file left it legally
  all-rights-reserved.

## v0.16.3 — the banner that never appeared (2026-07-19)

Reported: "the banner doesn't show", with an update genuinely published.

`UpdateChecker` checked at launch and then once every 24 hours. An app opened
*before* a release went out therefore cached "you're current" and would not look
again for a day — reopening the window changed nothing, because the check was
tied to process launch, not to the UI.

Worse, `UpdateBanner` rendered nothing when no update was known, and a view that
renders nothing never appears, so it could never trigger a check itself. The one
piece of UI whose whole job was noticing updates was structurally incapable of
looking for them.

- `checkIfStale(minInterval:)` re-checks when the update UI could appear,
  throttled to 15 minutes so opening the window repeatedly isn't a request storm.
- `UpdateBanner` wraps its condition in a `Group` and hangs `.task` outside it, so
  opening the main window or the popover *is* a check, whether or not a banner
  ends up being drawn. The banner then animates in.

## v0.16.2 — release notes without leaving the app (2026-07-19)

- **"What's new" opens a popover instead of a browser tab.** The notes were
  already in the release JSON the update check fetches, so opening GitHub to read
  a paragraph was a round trip out of the app for information it already had.
  `ReleaseNotesPopover` renders them inline — headings, bullets, and inline
  markdown via `AttributedString`, scrollable, 380pt wide.

## v0.16.1 — updates that actually update (2026-07-19)

"It makes me reinstall Rewisp all over again." Correct: the old "Get update"
button opened the DMG's download URL in a browser and left the user to mount it,
drag the app across, clear Gatekeeper, and re-grant Screen Recording. That is a
reinstall wearing an update's clothes, and the permission step made it look like
the app had broken.

- **`Updater.installUpdate`** downloads the DMG, then hands off to a detached
  script that waits for Rewisp to exit, swaps the bundle, clears the download
  quarantine flag, restarts the helper, and reopens the app. One click, nothing
  to drag.
- **The permission survives**, which is the whole reason this is safe:
  `bundle_python.sh` signs the helper with a fixed identifier from a pinned
  CPython, so its cdhash is identical between releases (verified: `21c3050c…`
  across a full rebuild). macOS hangs the Screen Recording grant on that hash, and
  the launchd agents reference an absolute path that does not change either.
- **Keeps the old copy** until the new one is in place, so a failure mid-copy
  restores rather than leaving the machine with no Rewisp.
- **Refuses to update a bundle outside /Applications** — a copy running from
  Downloads or a mounted image has no stable home to update into.
- **`UpdateBanner`** is now shared between the menu bar popover and the main
  window, with live download/install state and a manual-download fallback.

## v0.16.0 — uninstall from inside the app (2026-07-19)

- **Settings → Your data → Uninstall.** Removes the background helper, the startup
  items, the Screen Recording grant, your settings, and Rewisp itself. Everything
  goes to the **Trash**, never `rm` — this can remove months of screen history, so
  a misclick has to be recoverable.
  - "Also delete my memories" **defaults to off**, so uninstall-then-reinstall
    doesn't silently cost you your memory. The checkbox shows the real wisp count
    and folder size.
  - Order is load-bearing, and two of these were learned the hard way:
    1. `launchctl bootout` first — the daemon runs `KeepAlive`, so deleting its
       binary while the job is loaded makes launchd respawn it in a failure loop.
    2. `tccutil reset` **before** trashing the bundle. tccutil resolves a bundle
       identifier by looking the app up on disk; once it is gone it returns
       OSStatus -10814 and the permission rows are stranded in System Settings
       with no way to clear them.
    3. Trash the app last. macOS allows moving a running bundle, but nothing after
       that step can depend on files inside it.
  - No Finder scripting, despite that being the only way to get "Put Back":
    `NSWorkspace.recycle` cannot offer it, and the alternative triggers an
    Automation permission prompt. Asking for a *new* permission during an
    uninstall is the worse trade.

- **`ui/build.sh` was deleting the helper on every rebuild.** Its keep-list named
  `Resources/python` and `Resources/daemon` but not `MacOS/RewispBackend.app`, so
  each rebuild destroyed the helper. The running daemon survived only because its
  process held the deleted inode — the next restart would have killed it for good,
  and macOS pruned the Screen Recording grant the moment the binary vanished.
  Caught live on a working install. The list is now relative to `Contents/` and
  includes the helper.

- **`REWISP_NO_INSTALL=1`** — release builds no longer overwrite the installed
  copy. `make_dmg.sh` sets it, so cutting a release stopped silently upgrading the
  machine doing the cutting (which also made the in-app updater untestable).

## v0.15.1 — the permission prompt waits its turn (2026-07-19)

- **macOS's permission dialog no longer ambushes the welcome page.** The daemon
  called `request_screen_recording_permission()` the moment it started, which is
  at app launch — so the system prompt appeared before anything had explained what
  the access was for or that nothing leaves the Mac. macOS shows that dialog once
  per machine, so spending it on a confused "Deny" is expensive. The daemon no
  longer asks at all; the final onboarding page does, via `/request-permission`.
- **DMG window redesigned** (option C of four): a white card holding both icons on
  a lavender-grey field, caption below.
  - The old dark background was unusable: **Finder draws icon labels in black**
    regardless of the background image, so "Applications" was black-on-black.
    Light palette is a constraint, not a preference.
  - Caption used to collide with the icon labels — an icon's Finder position is
    its *centre* and the label hangs ~75px under it.
  - **Retina text.** Finder scales a PNG background to window size in points, so a
    720x480 PNG was upscaled 2x and every word drawn into it went fuzzy while
    Finder's own labels stayed sharp. `tiffutil -cathidpicheck` now combines the
    1x and 2x renders into an HiDPI TIFF.
  - `select {}` before saving the layout, so Finder doesn't persist a highlighted
    icon that shows up as a grey box behind the app on first open.

## v0.15.0 — the permission finally holds (2026-07-19)

Reported as "it's working. Now it's not working again." Capture would run for a
minute or two after granting Screen Recording, then silently stop, and the switch
in System Settings stayed on the whole time. Reinstalling never helped.

**Root cause: the app was destroying its own code signature at runtime.**
The bundled interpreter writes `__pycache__/*.pyc` beside every module it imports
— inside the app bundle. Per Apple TN2206, adding files to a signed bundle always
invalidates it, and macOS refuses to honour a TCC grant for a process whose
containing bundle no longer validates. So: grant, capture works, Python writes its
caches, the seal breaks, macOS revokes, capture stops. An endless loop, and it
would have hit every user identically.

- `PYTHONPYCACHEPREFIX` now points at `~/Rewisp/.pycache`. Verified: after
  sustained capture the bundle holds **0** `.pyc` files, `codesign --verify` still
  passes, and the grant survives a daemon restart.

**Second cause: the helper lived in the wrong directory.** It was in
`Contents/Resources`, which Apple designates for data — executables there are
treated as unsigned content. Apple's "Placing content in a bundle" puts helper
tools and apps in `Contents/MacOS`. Moved.

**Third cause, fixed on the way in:** the helper shipped as a bare mach-O signed
with `Identifier=-`, because `codesign --deep` from the app above it wiped the
identity. TCC had nothing durable to record, so the switch could be on while the
process stayed denied, and every rebuild silently revoked the grant. The helper is
now `RewispBackend.app` with `CFBundleIdentifier com.yashmit.rewisp.backend`,
signed with an explicit stable identifier, and `--deep` is gone from every build
path. Re-signing is deterministic (same cdhash), so grants persist across updates.

Lesson worth keeping: if a TCC permission reads as granted but the process is
denied, check `codesign --verify` on the containing bundle before anything else.

## v0.14.1 — the other permission card (2026-07-19)

v0.14.0 rebuilt the onboarding permission page and left the menu bar's card
untouched, so the popover still showed the old dead-end wording while onboarding
showed the new flow. Same lie, different surface.

- The menu bar card now mirrors onboarding: distinguishes "not granted" from
  "granted, helper restarting", asks macOS directly via `/request-permission`,
  and clears itself.
- **`ui/build.sh` was resurrecting a stale daemon.** It stashes
  `Resources/daemon` across rebuilds to protect the bundled runtime, then restored
  that copy instead of refreshing it from the repo. Result: the Swift app reported
  the new version while the Python helper beside it was old, so daemon-side fixes
  never reached the running helper. Caught live — an install reporting 0.14.0 had
  a daemon with none of 0.14.0's permission work in it. It now re-copies `rewisp/`
  and re-signs. (Distributed DMGs were never affected; `make_dmg.sh` always
  rebuilds that directory from source.)

## v0.14.0 — permissions that tell the truth (2026-07-19)

Reported from real use: "went through the entire process two times and both times
even though the permission was enabled, it says it wasn't enabled."

**Root cause.** `CGPreflightScreenCaptureAccess()` caches its answer for the life
of the process. A daemon that started without the grant reports "no permission"
forever, whatever the user does in System Settings. Worse, the watcher added in
v0.12 waited for `screen_permission == true` before restarting the daemon — the
restart being the only thing that could ever make it true. A deadlock: it waited
for a signal that its own action was required to produce.

- **Live probe** (`screen_recording_granted_live`) reads current state with no
  caching: macOS redacts `kCGWindowName` for processes without Screen Recording
  and un-redacts it the instant the grant lands.
- **The daemon restarts itself.** On seeing the live grant it exits; launchd's
  KeepAlive brings it back with the permission actually in effect. No UI involved,
  so it self-heals even if the app is closed.
- **`/status` gained `permission_pending`** — granted, but not yet applied — so the
  UI can say "applying it now" instead of insisting permission is missing.
- **`POST /request-permission`** triggers Apple's own prompt from the daemon (the
  process that actually captures; the UI app asking would grant the wrong thing).
  As close to in-window as macOS permits — there is no API to flip the switch.

**Onboarding reworked around it.**
- Permissions is now its own final page, with reassurance before the ask: macOS
  calls it "Screen Recording" but nothing is recorded, nothing leaves the Mac,
  and the kill list makes it blind where it matters. It sat mid-flow before, which
  meant people left for System Settings with unseen pages behind them.
- **Onboarding survives leaving and coming back.** Reopening the app used to go
  straight to the main window with onboarding gone for good. `showFrontDoor()`
  reopens it while unfinished, and the page index persists, so returning from
  System Settings lands you where you left off.

**Gatekeeper instructions corrected.** macOS 15+ removed the right-click → Open
bypass, so the install page was teaching a step that cannot work — matching the
report that "right-click and open still doesn't show the open anyway button". It
now documents the real route: try to open, get blocked, then System Settings →
Privacy & Security → **Open Anyway**.

**Landing page** gained a "Why I built this" section and a grants/contact section
with the email as selectable text next to the mailto button, since mailto quietly
fails for anyone without a configured mail client.

## v0.13.0 — the install actually holds together (2026-07-19)

A pass over the whole path a stranger walks: download, drag, open, onboard. Every
item here was reproduced on a torn-down machine, not guessed at.

- **Refuses to run from the disk image.** This was the big one. Rewisp writes
  launchd plists containing the absolute path to its bundled Python, so opening
  the copy *inside* the DMG wrote `/Volumes/Rewisp 4/…` — a mount point that dies
  on eject and never returns. The helper was then dead for good, and because macOS
  ties Screen Recording grants to a binary path, the permission they had already
  granted did not carry to the copy they later dragged over. `InstallLocation`
  now catches this (plus Gatekeeper's read-only translocation mount), offers to
  move the app to /Applications, de-quarantines it, and reopens from there.
- **Moving the app repairs itself.** `ensureDaemonRunning` compares the installed
  agent's path against this bundle instead of only asking "is something answering?"
  A helper left over from the DMG looks perfectly healthy until the eject, so
  health alone was never enough. Verified by sabotaging a plist to a dead
  `/Volumes` path and relaunching: repointed, HTTP 200.
- **Onboarding no longer eats your answers.** The Vault page and the browser
  picker posted to the helper while it was still starting, so a first-run user
  typed their name, saw a green "Saved to Vault", and had it silently dropped.
  Both now wait for the helper and report honestly if it truly failed.
- **No Terminal, anywhere.** Onboarding's setup button and the search panel's
  "Finish setup" still shelled out to `install.sh` in a Terminal window — the exact
  thing v0.12 existed to delete. Both provision in-process now, with progress and a
  real error if it fails. The dead `runInstaller` path is gone so it cannot return.
- **The menu bar stopped giving shell advice.** When the helper was down it said
  "Start it with: python3 -m rewisp daemon", a command that does not work on a
  stock Mac and names software we stopped depending on. It is a **Start Rewisp**
  button now.
- **Granting permission finishes the job.** The onboarding permission row arms the
  restart watcher, so the row turns green on its own — macOS only applies a Screen
  Recording grant on process restart, which is why "I gave permission and nothing
  happened" was the most common first-run complaint.

## v0.12.2 — the first-launch token race (2026-07-19)

Caught while rehearsing a cold install: the app showed "Daemon offline" in the
sidebar while the header said "Capturing", and `/status` answered fine from curl.
The daemon was never broken — the app could not authenticate to it.

`RewispAPI.token` was a lazily-initialized `static var token = { … }()`, which
Swift evaluates exactly **once**. On a first launch the app provisions the daemon
and reads `~/Rewisp/.api_token` before the daemon has written it, so the initializer
cached `""` permanently. Every later request sent an empty token, got 401, and had
the error swallowed by `try?` — indistinguishable from a dead daemon. It never
recovered until the app was quit and relaunched. This hit **every new install**.

- Token now re-reads from disk until it gets a non-empty value, then caches. One
  file read per request, only during the startup window.
- Any 401 reloads the token and retries once, so a re-provisioned daemon that mints
  a new secret recovers on its own.
- `provisionDaemon()` drops the cached token, since that is when a new one appears.

Lesson worth keeping: `static let`/lazy `static var` initializers are permanent.
Never use one to read state that another process creates asynchronously.

## v0.12.1 — docs catch up to the install rewrite (2026-07-19)

The in-app Help still told people to enable "Python" in Screen Recording, which
v0.12 renamed to "Rewisp Backend" — misdirecting exactly the users it was meant to
rescue. Help, MANUAL, README, BRIEF and this log brought in line with what shipped.

## v0.12.0 — it installs itself (2026-07-19)

The distribution release. A friend downloaded v0.11, asked a question, and got
"Could not connect to the server" — because the daemon never started, because a
stock Mac has no usable `python3`. Everything here follows from that.

- **Bundled Python runtime** — the app ships its own relocatable CPython 3.13.14
  (`Contents/Resources/python`) with pyobjc, numpy and model2vec already installed.
  Zero system dependencies. `scripts/bundle_python.sh` builds it; trimming tests,
  idlelib, tkinter and `__pycache__` keeps the DMG at 56 MB.
- **Self-provisioning on first launch** — `ui/Sources/Setup.swift` writes both
  launchd plists and bootstraps them the moment the app opens. No installer, no
  Terminal, nothing to run. Torn-down machine to daemon-up measured at ~3 s.
- **The helper is named "Rewisp Backend"** — the runtime binary is copied under
  that name, so the Screen Recording prompt says "Rewisp Backend" instead of
  "Python 3.13". People were denying a permission they couldn't identify.
- **Permission handling that actually clears** — macOS only applies a new Screen
  Recording grant on *process restart*, so the card used to stay orange after you
  granted it. The app now watches for the grant and kickstarts the daemon itself.
- **A normal-looking DMG** — branded background, app icon, arrow, Applications
  shortcut, toolbar hidden. `Install Rewisp.command` is gone (it contradicted the
  install page); `install.sh` still ships inside the bundle as the "Finish setup"
  fallback.
- **`site/install.html`** — a four-step illustrated walkthrough (CSS-drawn macOS
  dialogs) that the Download button opens, covering the Gatekeeper block and the
  permission prompt.
- **`scripts/fresh-test.sh`** — `backup` / `restore` / `status`, for rehearsing the
  real download-and-install path without losing live data.

Two packaging bugs found the hard way, both worth remembering:
1. `ui/build.sh` wiped `/Applications/Rewisp.app` on every rebuild, taking the
   bundled runtime and daemon with it. It now stashes and restores them.
2. DMG window layout needs the volume attached *without* `-nobrowse` (Finder
   can't script a hidden volume), and the background must be set with
   `POSIX file "$MP/.background/bg.png"` — the usual `file "Volume:.background:bg.png"`
   form throws `-10006`.

## v0.11.0 — connect your agents (2026-07-19)

- **MCP connector** — `python3 -m rewisp mcp` speaks the Model Context Protocol over stdio, so Claude Desktop / Claude Code / Cursor / VS Code / Windsurf / Gemini CLI can query your screen memory as five read-only tools (search_memory, get_context, get_day_summary, get_promises, get_page_changes). Read-only, fully local (no network listener), never spends your subscriptions, Vault excluded by default.
- **Connect agents** is a top-level sidebar page: a live "Connected" banner (heartbeat when an agent queries), an animated demo, and per-client setup — one-click "Add to Claude Desktop" (writes the config), plus copy/download for every other client. Honest note that ChatGPT connectors are remote-only.
- **Numbers precision fix** — the "Tracked" card was charting garbage (ad prices, file sizes, progress bars). Now the label must BE a personal metric (weight, grade, steps, heart rate…); money/counts and noise surfaces (streaming/search/AI/Finder) are excluded. Purged 291 junk rows. 147 tests.

## v0.10.0 — it learns how you forget (2026-07-18)

The Forgetting Model ships, plus a data-driven refinement sweep over live usage.
- **The Forgetting Model** — failed searches and re-asked questions are mined as documented forgetting events; a per-category signature (names/numbers/links/dates/places) is fit from them. "How you forget" card in Settings → Your data draws your five animated decay curves with half-life dots. "About to fade" gives single-visit wisps one rescue mention in the digest at the spaced-repetition sweet spot; the ~3rd lookup of the same stable fact auto-pins it for instant deterministic recall (time-dependent questions can never pin — caught live).
- **Answers** — "what did I do today" fixed (activity questions live purely off the time window; no more portfolio-PDF/old-episode bleed); long answers render as one bold lead + scannable bullets with all detail preserved (NNG-grounded); thin on-device day-summaries auto-escalate.
- **Digest resilience** — engine-chain fallback (was Claude-only; a session limit killed the night) + 30-min retry backoff until an engine answers.
- **Collection quality (from live data)** — Dock/Mission Control never captured; LockDown Browser kill-listed; sub-40-char subtitle fragments dropped; 2,212 junk number-series purged (engagement counters, media pages, K/M fragments blocked).
- **Nudge pill** — pinned to the primary display (was following keyboard focus = "random places"), notch-safe, clean single-surface restyle.
- **Quality gate** — scripts/check.sh (pytest + imports + build + endpoint smoke) as a pre-push hook.
- Tests 108 → 132.

## v0.9.0 — promises that keep themselves (2026-07-16)

The refinement cycle: multiple precision passes over the v0.8 features, grounded
in memory-science research (prospective-memory diary studies, re-finding logs).
- **Promises precision redesign** — live use showed ~95% false positives (AI assistants' "I'll fix that", ad copy, dictation garble). Now source-gated (AI-chat surfaces/IDEs/system UI never produce promises; Notes/Mail/Slack/gmail = authored bar; generic web = strict bar) + evidence-scored with hard rejects (questions, negation, hedges, ad lexicon, instructional copy, clipped tails). All 16 live false positives pinned as regression tests.
- **Due-day promise reminders** — confirming a promise opts it into a pill on its due day (action + deadline, once per day, overdue variant). The detect → confirm → remind → done loop is closed. Live-verified.
- **Near-miss rescue** — a failed search now attaches the 3 closest moments instead of a bare "Not found" (re-finding research: ~40% of queries are re-finds; people misremember their own wording ~30% of the time).
- **Names bank** — "who …" questions inject recent episodes' people/org names into context (names = #1 retrospective failure).
- **Numbers** — labels normalize to their noun core ("My weight today" → "weight") so phrasing variants merge; lookup regex fix + wider phrasings.
- **Delta** — menu-bar/browser chrome no longer pollutes diffs.
- **Precog** — history chips need semantic proximity to the screen; junk queries never re-offered.
- Tests 84 → 108.

## v0.8.1 — polish (2026-07-14)

Post-v0.8 polish from a full manual UI sweep. No new features; everything above
still holds.
- **Help center rebuilt** — was a plain rendered manual; now a looping animated search demo, a "Start here" quick-start row, an FAQ of expandable Q&As, a keyboard-shortcuts card, troubleshooting, and the full manual collapsed + searchable (search filters FAQ + manual together).
- **Memory** — delete a Confirmed fact from the tab (hover → ✕), not just Pending; fuzzy de-dupe so the digest stops re-proposing reworded facts it already learned.
- **Today** — clearer stat strip (live green/orange capture dot, "top app" label).
- **Onboarding** teaches the v0.8 reasoning features.
- **Chat** keeps the full Delta diff in history, not just the summary line.

## v0.8 — intelligent memory (2026-07-14)

The cycle that made Rewisp reason over its own memory, not just store it. All
local, all free. First automated test suite landed here too (79 pytest).

- **Semantic Memory (#0)** — local static embeddings (model2vec potion-retrieval-32M, 512-dim, pure numpy) on every wisp; retrieval fuses FTS + vector rank via RRF. Brute-force cosine (no vector-index extension at this scale). Fail-safe: offline → FTS only. `delete_captures` is the single cascade choke point for forget/kill/retention.
- **Delta Memory (#1)** — `page_key` (normalized URL / app+title) identifies a page across time; fuzzy line-diff (with numeric-change detection) answers "what changed on this page?" deterministically. GET `/delta`.
- **Déjà Vu (#2)** — proactive recall: reuse the capture's embedding, vector-search history, fire on strict gates (cosine, >24 h old, different context). Reusable nudge-pill UI (slide-in, hover-expand, connector line, 👍/👎). Off by default + "Send test nudge". Snippets strip OCR menu-bar chrome.
- **Promises (#3)** — catch commitments off-screen (first-person + imperatives, with or without a deadline; boilerplate filtered), hold as Pending, surface on Today as paper slips (owe / waiting), confirm → done crumple, overdue red.
- **Dream + Reinforcement (#4)** — nightly consolidation of aged wisps into `episodes` (session/page clustering, extractive summaries, embedded + FTS'd), mixed into answer context. Recall bumps `recall_count`; `w=recall_count·exp(-days/90)` is a 3rd RRF signal; reinforced wisps exempt from retention (2× cap). MemoryLayersCard sediment viz.
- **Precognition (#5)** — guessed questions from the current screen + query history (template detectors + embedding-ranked history), shown as shimmer chips; taps tracked. Fuzzy de-dupe.
- **Numbers Over Time (#6)** — recurring label+number → tracked series (≥3 distinct-ts readings, variance); rejects credentials, ids, years, menu-bar chrome; requires a unit or metric word. SeriesCard sparkline. Deterministic "how has X moved?"
- **Safari autofill fix** — WebKit ignores AXValue writes unless the field is focused first; focus-then-write-then-verify. Chromium unaffected.
- **Bug sweep** — promises/series cards never loaded (`.task` on a Group that resolved to EmptyView); precog duplicate chips; noise series from battery %.

### Gotchas (v0.8)
11. **`.task` never fires on a view that resolves to `EmptyView`** — gating a poll behind "no data → EmptyView" means it never fetches, so the card stays empty forever. Put `.task` on an always-present container (a `VStack` that conditionally shows a `Card` inside).
12. **WebKit silently ignores AX `AXValue` writes** (returns success `0`, value unchanged) unless the element is focused first. Verify writes by reading the value back — the return code lies. Chromium accepts writes without focus.
13. **OCR reads the menu bar first**, so raw snippets/series start with "App File Edit View … Help 43% Tue Jul 14" chrome — strip it before display, and reject it as a tracked number (battery % became a bogus series).

---

## Post-v0.1 releases (v0.2 → v0.7, 2026-07-09 → 07-12)

Shipped after the v1 phase plan above. The phase checklist is frozen as history;
this is the running release log.

- **Engine fallback chain** — `Auto` = Apple on-device → Claude (Claude Code) → Codex (ChatGPT Plus) → Gemini (free key) → Ollama. Falls through when one whiffs; refuses paid API-key env vars; answers badge the engine.
- **Apple on-device prompt overhaul** — removed the worked example that was being regurgitated as fake facts; parenthesized format cues; whiff-detection escalates empty/echoed/hedged answers. ~4 → ~11/15 strong answers vs a Claude gold set.
- **Form autofill (M1 + M2)** — detect every field over AX (crash-isolated `axhelper`), gather from Vault, show per-field with copy, then write into the page. Never submits; never card/CVC/password. Address parsing; single-field "Find mine."
- **Touch ID Vault** — Vault locked behind a fingerprint; ingest extended to .rtf.
- **Multi-browser capture** — Chromium family (Chrome, Arc, Edge, Brave, Vivaldi, Opera, Dia) + Safari get URL trigger + URL kill list + incognito detection; Firefox title-only.
- **Main window + Settings redesign** — Today dashboard, chat sessions, and a sectioned Settings sidebar (Answers / Local model / Cloud & keys / Digest / Notifications / Privacy / Your data / Help). Unified wisp logo across icon/animation/UI. Markdown rendering fixed app-wide (no literal `**bold**`).
- **Onboarding** — welcome → privacy → permissions → Vault setup page → animated feature demos.
- **In-app Manual + bug report** — no GitHub links; built into the app.
- **Search panel polish** — SwiftUI scale+fade entrance, answer-cutoff fix, and the non-activating click-twice fix (gotcha #9).
- **Local model support** — hardware auto-detect + best-fit model download (MLX), later removed; Ollama remains as the local engine. Offline/unlimited path still open.
- **Benchmark harness** — LLM-as-judge, Apple vs Claude across 15+ questions, gold-answer caching.
- **Landing page rework** — split into html/css/js, live in-browser feature demos (autofill, engine chain, digest, time), fresh screenshots, CDN cache-busting (gotcha #10).
- **Self-capture exclusion** — daemon no longer indexes Rewisp's own UI (was polluting retrieval with your own questions).
