# Rewisp — Build Progress

**Current status:** Phases 0–4 built and verified. Phase X (Yashmit's batch) largely done: panel expand fixed + auto-verified, Esc everywhere, menu bar icon state, main window (Chat/Vault/Memory/Settings), Apple on-device model for quick answers with Claude fallback, retrieval overhaul (verified: "what do i have due on july 12th" → correct homework answer), API token auth, repo reorganized.
**Next up:** first automatic Digest (tonight 9 PM), 5-question success test after 2 days of data, Phase 5 extras (export, weekly report, form detector).

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
- [ ] Form detector + info panel from Vault (deferred — the Ask panel already
      answers "what's my X" from the Vault with a Copy button)
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
