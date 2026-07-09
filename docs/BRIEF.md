# Rewisp — Project Brief

An ambient memory app for macOS. It watches the user's screen, remembers everything as searchable text, and uses Claude as the reasoning layer to answer questions about the user's own digital life.

Owner: Yashmit. Single user. Runs only on his Mac. Never leaves his machine except calls to Claude.

---

## 1. Product summary

Rewisp captures screenshots of the screen when something meaningful changes, OCRs them locally, stores text only, and deletes the images. A nightly job (Digest) summarizes the day, finds loose threads, and updates a learned memory file. The user asks questions through a menu bar dashboard or a global hotkey search, and Claude answers using the screen history, an uploaded personal info vault, and learned memory.

Tagline idea: "Your Mac remembers everything you see."

## 2. Hard constraints (never violate)

1. **Zero extra cost.** All AI calls route through Claude Code / the user's Claude Pro subscription. Never use a raw Anthropic API key. Check that no `ANTHROPIC_API_KEY` env var is set before shipping (it silently bills the API instead of the subscription).
2. **At most ONE automated Claude call per day** (the Digest). Interactive Ask calls are fine because the user triggers them. No polling, no background AI loops.
3. **Privacy first.** Screenshots are deleted immediately after OCR. Only text is stored. Everything stays local except text sent to Claude for Digest and Ask.
4. **Kill list is absolute.** Never capture: Messages, WhatsApp, password fields, banking/finance sites, private/incognito windows, plus anything the user adds. When a kill-list app/site is frontmost, capture pauses fully.
5. **The app fills forms but NEVER submits them.** Human always clicks submit.
6. **Never store in the Vault or Store:** passwords, SSN, full card numbers, or any credential.

## 3. Architecture (6 core pieces)

```
Capture (daemon) --> Store (SQLite) --> Digest (nightly Claude call)
                          ^                    |
                          |                    v
User uploads --> Vault    +----> Ask <---- Memory (learned facts)
                                  |
                          Menu bar UI + hotkey UI
```

### 3.1 Capture (Python daemon)

Smart triggers, not a timer:
- **Window/app switch** — capture on frontmost app change (macOS Accessibility API / NSWorkspace notifications via pyobjc).
- **New URL** — when the browser's active tab URL changes. Browser is **Dia** (Chromium-based). Day-one task: test whether Dia supports AppleScript tab/URL queries like Chrome. If yes, use it. If no, fall back to window title (page title) plus OCR of the visible address bar.
- **Scroll settle** — user stops scrolling for ~2 seconds, capture once.
- **Idle guard** — no keyboard/mouse input for 5 minutes → stop capturing until activity resumes.

Dedupe layer:
- Before saving, downscale the screenshot to a small thumbnail and compare to the previous capture. If less than ~5% of pixels changed, discard. Kills "same email open for 20 minutes" spam.

Per capture, store:
- OCR text (Apple Vision framework via pyobjc — local, free, fast)
- App name, window title
- URL if browser (plus page title)
- Timestamp
- Then **delete the image file immediately**.

Expected volume: roughly 300–800 captures/day. Text only, a few MB/day.

macOS permissions needed: Screen Recording + Accessibility. The app should detect missing permissions and show a friendly setup guide.

### 3.2 Store (SQLite)

Single local SQLite database with FTS5 full-text search. Suggested schema:

```sql
CREATE TABLE captures (
  id INTEGER PRIMARY KEY,
  ts DATETIME NOT NULL,
  app TEXT NOT NULL,
  window_title TEXT,
  url TEXT,
  ocr_text TEXT NOT NULL
);
CREATE VIRTUAL TABLE captures_fts USING fts5(ocr_text, window_title, url, content=captures, content_rowid=id);

CREATE TABLE summaries (      -- written by Digest, kept forever
  id INTEGER PRIMARY KEY,
  date DATE UNIQUE,
  summary_md TEXT,            -- what the user did that day
  threads_md TEXT,            -- loose/unfinished things
  time_report_json TEXT       -- app/category time breakdown
);

CREATE TABLE chats (          -- user's conversations with Ask
  id INTEGER PRIMARY KEY,
  ts DATETIME,
  role TEXT,                  -- 'user' or 'assistant'
  content TEXT
);

CREATE TABLE entities (       -- silent knowledge graph, v1.5+
  id INTEGER PRIMARY KEY,
  name TEXT, kind TEXT, first_seen DATETIME, last_seen DATETIME, notes TEXT
);
```

Retention rules (run daily, locally, no AI):
- `captures` rows older than **6 months**: delete.
- `chats` rows older than **6 months**: delete.
- `summaries`: keep **forever**.
- Memory file: keep forever (user-editable).

### 3.3 Vault

A plain folder (e.g. `~/Rewisp/vault/`) where the user drops files about himself: resume, project writeups, standard application answers, course info. Supported: .md, .txt, .pdf, .docx (extract text on ingest). Indexed into its own FTS table.

Rule: Vault is trusted truth. If Vault and screen data conflict, Vault wins.
Rule: refuse/warn if a Vault file appears to contain passwords, SSN, or card numbers.

### 3.4 Memory

A single markdown file, e.g. `~/Rewisp/memory.md`, with two sections:

```markdown
## Confirmed
- Prefers short answers
- Prioritizing robotics internships right now

## Pending (approve or delete)
- Seems to study best late at night
```

- Digest proposes new lines into **Pending**.
- The user moves lines to Confirmed (or deletes) via the settings UI or by editing the file directly.
- Confirmed memory is included as context in every Ask call.
- Plain text, always human-editable. No black box.

### 3.5 Digest (the one daily automated Claude call)

Schedule: **9:00 PM local** via launchd. If the Mac was asleep at 9 PM, run on next wake (catch-up flag).

Input assembled locally (no AI cost): the day's captures compressed by simple local heuristics (dedupe repeated text, group by app/hour), the day's chats, yesterday's open threads.

One Claude call (via Claude Code non-interactive / Agent SDK on the Pro subscription) that returns structured output:
1. **Daily summary** — what the user worked on, read, decided (writes `summaries.summary_md`).
2. **Loose threads** — emails opened but not replied to, applications started but not finished, tabs/tasks abandoned; carry over unresolved threads from prior days (writes `summaries.threads_md`).
3. **Subtext notes** — for important emails/messages seen on screen, short tone/meaning notes ("this rejection leaves the door open").
4. **Memory proposals** — durable facts/preferences learned from today's chats, appended to Memory's Pending section.
5. **Time report data** — computed locally from app/timestamp data (no AI needed); Digest may add a one-line narrative.

Cost note: non-interactive subscription usage draws from a separate monthly automation credit, then bills API rates. One call/day should fit inside the credit. Add a counter in settings showing Digest calls this month, and log token sizes. If a single Digest input would be huge, truncate locally rather than making multiple calls.

### 3.6 Ask

Interactive question answering, routed through Claude Code on the Pro plan.

Pipeline for a question:
1. Parse time phrases locally ("last Tuesday afternoon", "right before my quiz" via summaries lookup) into a time filter.
2. FTS search over captures + summaries + Vault, filtered by time if given.
3. Build context: top matching snippets (with timestamps/apps/urls), relevant Vault chunks, Confirmed memory.
4. One Claude call. Answer must cite sources: which app, when, which capture/Vault file.
5. Show answer with sources in the UI. Offer "Continue in chat" which opens a threaded conversation (subsequent turns keep the thread context).
6. Save the exchange to `chats`.

## 4. UI spec

Style: clean, minimal, Apple-native feel. Light/dark toggle only (follow system by default). No other theming.

### 4.1 Menu bar icon (always visible)
Click opens the **mini dashboard** popover:
- Search bar at top ("Ask your memory anything")
- "Today so far" — live short recap (from local heuristics before 9 PM, from Digest after)
- "Loose threads" — current open threads list
- Buttons: Pause capture, Settings
- Search results render inline in the panel with sources; "Continue in chat" expands to a chat view.
- Icon shows a subtle state: capturing / paused / kill-list-active.

### 4.2 Global hotkey (Cmd+Shift+Space, rebindable)
Spotlight-style floating bar over any app:
- Type question → instant answer with source line.
- Enter = continue in chat (opens dashboard chat). Esc = dismiss.
- Shares the exact same Ask backend as the dashboard.

### 4.3 Settings window
- Notifications: **Silent / Daily ping / Real-time** (default: Daily ping = one evening notification with recap + threads; Real-time adds form-detector nudges).
- Kill list editor (apps and URL patterns). Preloaded defaults: Messages, WhatsApp, banking/finance domains, password manager apps, private/incognito windows.
- Pause hotkey configuration + "delete last 10 minutes" button.
- Retention status (DB size, oldest raw capture).
- Memory review UI (approve/delete Pending lines).
- Vault folder shortcut + reindex button.
- Digest usage counter (calls this month).
- Export button.
- Light/dark toggle.

### 4.4 Tech choice for UI
Prefer native: **SwiftUI menu bar app** talking to the Python daemon over a localhost socket, OR a pure-Python approach (rumps + a small web view) if faster to ship. Builder picks the least painful path; the daemon/DB design stays identical either way.

## 5. Feature list (v1)

1. Smart capture (all triggers + dedupe + idle guard)
2. Kill list + pause hotkey + delete-last-10-minutes
3. Store with FTS + retention jobs
4. Vault ingest + indexing
5. Memory file with Pending/Confirmed flow
6. Digest at 9 PM with catch-up
7. Ask with time-phrase search and sources
8. Mini dashboard popover
9. Global hotkey search
10. Daily recap (on demand + optional evening notification)
11. Loose thread tracker
12. Weekly time report (local computation; simple bar breakdown by app/category: classes, job hunt, projects, browsing)
13. Export everything (summaries + memory + captures as markdown/CSV to a folder)
14. Form detector + info panel: OCR spots form-like keywords (name, address, email fields, "application") → optional notification → panel shows the user's standard answers from Vault ready to copy. Detector respects the notification setting.

## 6. v2 (do NOT build yet, design for it)

- **Smart-fill browser extension** for Dia/Chromium: reads DOM field labels; easy fields (name, email, address, school) filled by local rules from a localhost Vault server; essay fields drafted by Claude using Vault context; fills and highlights, never submits.
- Knowledge graph surfacing (entities table → people/repo pages).
- Richer proactive nudges.

## 7. Build plan (phases, in order)

**Phase 0 — Dia browser test (MANDATORY FIRST STEP, before any other code)**
- Before writing anything else, test whether the Dia browser supports AppleScript queries for the active tab's URL and title (try Chrome-style AppleScript first, since Dia is Chromium-based; also check for a Dia-specific scripting dictionary).
- Also test grabbing Dia's frontmost window title as the fallback signal.
- Write the results into `PROGRESS.md` under "Blockers / open questions": which method works, exact commands used, and sample output.
- Decision gate: if AppleScript works → Capture uses it for the URL trigger. If not → Capture uses window title + address-bar OCR fallback.
- Do NOT start Phase 1 until this test has real results from the actual machine. No assumptions.

**Phase 1 — Capture + Store (prove the spine)**
- Daemon with window-switch trigger only, Vision OCR, SQLite insert, image deletion.
- Add URL trigger (using the method decided in Phase 0), scroll settle, idle guard, dedupe.
- Kill list enforcement + pause hotkey.
- Success test: run for 2 hours of normal use, then find a known page via `sqlite3` FTS query.

**Phase 2 — Ask (terminal first)**
- CLI: `rewisp ask "what was that github repo from tuesday"` → FTS + time parse → Claude via Claude Code → answer with sources.
- Success test: correctly answers 5 real questions about the last 2 days.

**Phase 3 — Digest + Memory + Vault**
- launchd job at 9 PM + wake catch-up. Summaries, threads, memory proposals written.
- Vault ingest + inclusion in Ask context.
- Retention job.

**Phase 4 — UI**
- Menu bar icon + mini dashboard (search, recap, threads, pause, settings).
- Global hotkey window.
- Settings window with everything in 4.3.

**Phase 5 — Polish features**
- Weekly time report, export, form detector + info panel, notifications setting.

Each phase must fully work before the next starts.

## 8. Edge cases and rules for the builder

- Multiple monitors: capture the display containing the frontmost window only.
- Screen locked / display asleep: no captures.
- Very long OCR text: cap per-capture text at a sane size (e.g. 10k chars).
- Dia browser uncertainty: test AppleScript support first; fall back to window title + address-bar OCR; log which mode is active.
- Clock changes / time zones: store UTC, display local.
- DB corruption safety: WAL mode, daily local backup of summaries + memory into the export folder.
- If Claude Code auth is missing/expired, Ask and Digest show a clear "sign in to Claude Code" message instead of failing silently.
- All prompts sent to Claude must instruct it to answer only from the provided context and to say "not found in your memory" rather than guess.
- Never auto-update the Confirmed memory section; only Pending.

## 9. Progress tracking (required)

On day one, create a separate file `PROGRESS.md` in the project root. Rules:

- It contains the full build plan as a checklist: every phase from section 7, broken into its individual tasks, plus each success test as its own item.
- Use markdown checkboxes: `- [ ]` for not done, `- [x]` for done.
- Each completed item gets a date when checked off, e.g. `- [x] Window-switch trigger working (2026-07-08)`.
- Update `PROGRESS.md` at the end of EVERY working session, before doing anything else. Never mark an item done unless it was actually run and verified on the machine.
- Success tests can only be checked off after they pass for real, not after the code is merely written.
- Keep a short "Current status" line at the top (e.g. "Phase 2 in progress: Ask CLI returns answers but sources are missing") and a "Next up" line so any new session knows exactly where to resume.
- Add a "Blockers / open questions" section at the bottom for anything unresolved (e.g. the Dia AppleScript test result goes here first).
- Never delete checked items; the file is the permanent timeline of the build.

At the start of every new session, read `PROGRESS.md` first and resume from "Next up."

## 10. Definition of done (v1)

- Runs all day at <5% average CPU, <300 MB RAM.
- "What was that repo I scrolled past last Tuesday?" answered correctly with source.
- Kill list verified: open Messages, confirm zero rows captured.
- Digest ran automatically and produced a readable recap + threads.
- Memory learned at least one correct fact from chats, via Pending approval.
- Export produces a folder a human can read without the app.
- Total spend beyond the Pro subscription: $0.
