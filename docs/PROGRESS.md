# Rewisp — Build Progress

**Current status (v0.8.0, 2026-07-14):** Phases 0–5 shipped + the "intelligent memory" cycle. In daily use (~180+ wisps/day, 3800+ wisps, ~500 episodes). v0.8 adds seven reasoning features (semantic search, delta, promises, numbers, precognition, dream/reinforcement, proactive-recall nudges) plus the first pytest suite (79 tests) and a Safari autofill fix. 10 releases (v0.1.0 → v0.8.0).
**Next up:** custom "Rewisp AI model" training (~week-long); MCP connector to expose Rewisp memory to external agents (both in `todo.md`, not started). Re-adding a bundled offline/unlimited local model is an open option.

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
