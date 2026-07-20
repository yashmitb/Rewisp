# Rewisp — Project Brief (current state)

An ambient memory for macOS. Rewisp quietly captures the **text** of what you see, keeps it local, and lets you ask your past anything. Private by construction — screenshots never touch disk.

Owner: Yashmit. Single user, his Mac only. Nothing leaves the machine except the prompt of a question or the nightly digest, and only to the engine you choose.

**Current version: v0.17.2** (30 releases across 2026-07-08 → 07-19). In daily use (~180+ wisps/day, 11,000+ wisps). 147 tests.

The arc so far: v0.8 shipped the "intelligent memory" cycle (semantic search, delta, promises, numbers, precognition, dream/reinforcement, nudges); v0.9 was the precision cycle, closing the promise loop with due-day reminders and failed-search near-miss rescue; v0.10 added the Forgetting Model; v0.11 exposed the whole memory to external agents over MCP; v0.12 made it installable by someone who isn't a developer — the app bundles its own Python runtime and provisions its background helper on first launch, so there is nothing to run and no system dependency.

**Launched** on Product Hunt 2026-07-20: **#5 product of the day, 187 upvotes**. First outside contribution ([#1](https://github.com/yashmitb/Rewisp/pull/1)) merged the same day.

> This file describes what Rewisp *is today*. For the build timeline and per-task history, see `PROGRESS.md`. For the manual, `MANUAL.md`. For the threat model, `SECURITY.md`.

---

## 1. Product summary

Rewisp captures a screenshot when something meaningful changes, OCRs it locally with Apple Vision, stores the **text only**, and discards the image in memory. A menu bar app + a `⌘⇧Space` search panel let you ask questions about your own screen history, a personal-info Vault, and a learned memory file. A nightly digest summarizes the day and surfaces loose threads.

Tagline: *"Your Mac, with a memory."*

## 2. Hard constraints (never violate)

1. **Never bill an API key.** All AI runs through subscriptions (Claude Pro via Claude Code, ChatGPT Plus via Codex CLI) or free keys (Gemini) or fully on-device (Apple / local). Refuse to run an engine if its paid API key env var is set (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) — that silently bills the API instead of the subscription.
2. **At most ONE automated cloud call per day** (the digest). Interactive Ask calls are user-triggered, so they're fine. No polling, no background AI loops.
3. **Privacy first.** Screenshots are OCR'd in memory and released — never written to disk. Only text is stored, locally, in one SQLite file.
4. **Kill list is absolute.** Never capture: Messages, WhatsApp, password managers, banking/finance, private/incognito windows, plus anything the user adds. Kill-list app/site frontmost → capture pauses fully.
5. **The app fills forms but NEVER submits them.** The human always reviews and sends. It never fills passwords, card numbers, CVC, or SSN.
6. **Never store credentials** in the Vault or Store: passwords, SSN, full card numbers. Refused at ingest.

## 3. Architecture

```
Capture (Python daemon) --> Store (SQLite FTS5) --> Digest (1 cloud call/night)
                                  ^                        |
                                  |                        v
     User files --> Vault (Touch ID) --> Ask <---- Memory (learned facts)
                                          |
                        Form autofill  ---+---  SwiftUI menu bar app
                        (AX, never submit)      + ⌘⇧Space search panel
```

- **Capture daemon** — Python/pyobjc, 0.5s poll. Smart triggers: app-switch, URL-change (Chromium family + Safari via AppleScript, Firefox title-only), scroll-settle, heartbeat. Idle guard + thumbnail-diff dedupe. Self-capture excluded (won't index Rewisp's own UI).
- **OCR** — Apple Vision, max-recall (revision 3 + auto language, tiled 2×2 pass, reading-order reassembly). Image lives only in memory.
- **Store** — SQLite with FTS5 (bm25 rank, WAL). Retention 6 months for captures/chats; summaries + memory kept forever. Daily local backup.
- **UI** — native SwiftUI (16 source files), talks to the daemon over a token-gated localhost API (`127.0.0.1:43117`, `X-Rewisp-Token`).
- **Isolation** — Accessibility calls crash Chromium, so form detection runs in a crash-isolated `rewisp axhelper` subprocess; the daemon never touches AX directly.

## 4. Feature set

### Thinking over memory (v0.8 — all local, all free)
- **Semantic search** — meaning-based retrieval (model2vec embeddings + FTS fused via RRF); "burnout" finds "exhaustion".
- **Delta** — every page version stored as text, so "what changed on this page?" diffs them (added/changed/removed, numeric moves).
- **Promises** — commitments caught off-screen, held on Today until confirmed + done.
- **Numbers over time** — recurring label+numbers become tracked sparklines; "how has my weight moved?".
- **Precognition** — suggested questions guessed from the current screen + query history.
- **Dream + reinforcement** — nightly consolidation into episodes; asked-about wisps strengthened and retention-exempt.
- **Proactive recall** — a nudge pill surfaces a relevant past memory (off by default). Detection local; nudges never call the cloud.
- Single cascade delete choke point so forget/kill/retention purge every derived table.

### Answering
- **Engine chain with auto-fallback:** Apple on-device → Claude → Codex (ChatGPT Plus) → Gemini (free) → Ollama. Falls through when one comes up thin. `Auto` picks the best you've set up; answers badge which engine replied.
- Apple on-device Foundation Model prompt heavily tuned (no hallucination, synthesizes, multi-thread coverage), with whiff-detection that auto-escalates to a stronger engine.
- Vault facts answered **deterministically** — exact value, no model involved.
- Local time-phrase parsing ("yesterday", "this morning"); FTS retrieval with capture dedupe, recent-verbatim inclusion, and time-window fallback.
- Structured answers: ANSWER / DETAIL / SOURCE / TIME / COPY.
- Benchmark harness (LLM-as-judge) for comparing engines.

### Privacy
- Kill list (apps + URL patterns), hot-reloadable, with incognito detection across Chromium + Safari.
- Credentials refused at Vault ingest. "Forget last 10 minutes" button.

### The Vault
Ingest .md / .txt / .docx / .pdf / .rtf, FTS-indexed, **Touch ID locked**, treated as trusted truth (Vault wins over screen data on conflict).

### Form autofill
`⌘⇧Space` on a page detects every field over Accessibility, gathers values from the Vault, shows them per-field with copy, and **fills into the page — never submits, never cards/passwords**. Address parsing (one line or separate). Single-field "Find mine."

### Nightly digest
One cloud call at 9 PM: daily summary, loose threads, subtext notes, memory proposals. Configurable hour + frequency, wake catch-up, "run now."

### Memory you control
Plain markdown, Pending/Confirmed approval flow, UI tab. Confirmed memory is context in every Ask. Never auto-confirms.

### Time tracking
Minutes per app, weekly report, computed locally from timestamps.

### UI
- **Menu bar app** (LSUIElement), state-aware icon (capturing / paused / kill-list / down).
- **Search panel** — Spotlight-style, fades in, grows with the answer, non-activating (a click into the app behind lands first try), keep-open pin.
- **Main window** — Today dashboard (greeting, digest, loose threads, weekly bars), Chat, Vault, Memory, sectioned **Settings** (Answers / Local model / Cloud & keys / Digest / Notifications / Privacy / Your data / Help), in-app Manual + bug report.
- **Onboarding** — welcome → privacy → permissions → Vault setup → animated demos.

### Connect agents (MCP)
`python3 -m rewisp mcp` exposes memory to Claude Desktop / Claude Code / Cursor / VS Code / Windsurf / Gemini CLI as five **read-only** tools. Local stdio (no network listener), never calls a cloud engine, Vault excluded by default. A top-level "Connect" tab has a live connection banner, per-client setup (one-click for Claude Desktop), and an animated demo.

### Distribution
DMG (daemon bundled inside the app + installer), `/Applications`, launchd agents (capture always-on + 9 PM digest), auto-update via GitHub Releases. Landing page at https://yashmitb.github.io/Rewisp/ (GitHub Pages; html/css/js with live in-browser feature demos).

## 5. Status & roadmap

**Shipped:** Phases 0–5 (capture, ask, digest/memory/vault, UI, distribution) plus the post-v0.1 batch (engine chain, form autofill, Touch ID Vault, multi-browser, main-window redesign, onboarding, landing-page rework). Working and in daily use.

**Known limits:**
- Apple's on-device 3B model has a quality ceiling + run-to-run variance; currently defaulting to Gemini (fast + sharp). A bundled offline/unlimited local model (MLX) was built then removed — that path is still open.
- macOS-only (cross-platform deferred).

**Next (see `todo.md`):**
- Train a custom "Rewisp AI model" (~week-long effort).
