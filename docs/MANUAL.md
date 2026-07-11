# Rewisp — User Manual

Your Mac remembers everything you see. Every glimpse of your screen becomes a
**wisp** — text only, stored on this Mac. Ask anything later and Rewisp *revisits*
those wisps to answer. Quick answers run on Apple's on-device model ($0, nothing
leaves the Mac); hard questions and the nightly digest use a stronger engine
(Claude / ChatGPT / free Gemini / Ollama — whichever you've set up, $0 extra).

---

## Daily use

### Ask anything, from anywhere
- **Cmd+Shift+Space** — floating search bar over any app.
  Type a question → Enter. The bar grows as the answer streams in.
  **Esc** clears first, closes when empty. **Copy** button copies just the answer value.
  A small badge shows which model answered (**Apple on-device** or **Claude**).
- **Menu bar icon** — same search, plus "Today so far" (time per app) and
  "Loose threads". **Esc** closes the popover. The icon itself shows state:
  filled = capturing · pause badge = paused · hand = kill-list app frontmost ·
  hollow = daemon not running.
- **Main window** (menu bar → gear or vault icon) — full chat with history,
  Vault manager, Memory review, and Settings.

Questions understand time: *"what was that repo last tuesday"*, *"the pdf from
yesterday morning"*, *"what did I read 3 days ago"*.

### Which AI answers?
| Question type | Engine | Cost |
|---|---|---|
| Hot search / chat | Apple on-device model (macOS 26) | $0, fully local |
| On-device unavailable or can't find it | Engine chain below | $0 extra |
| Digest (9 PM default, frequency configurable) | Engine chain below — the only automated call | $0 extra |

**Engine chain** (Settings → AI engine): Auto tries **Claude Pro** (best), then
**ChatGPT Plus** via the Codex CLI (`npm i -g @openai/codex`, sign in once), then
**free Gemini** (paste a free key from aistudio.google.com/apikey into Settings —
strong answers, no install, no paid API), then **free local Ollama** (install from
ollama.com, `ollama pull llama3.1:8b`). Ollama is unlimited and never leaves your
Mac but is weaker; Gemini sends your memory text to Google only when it answers.
Subscriptions/free keys only — Rewisp refuses to run if ANTHROPIC_API_KEY or
OPENAI_API_KEY is set, so you can never be silently billed per-token.

**Benchmark your engines**: `python3 -m rewisp bench` runs a set of questions
against your real memory through every engine you've set up and prints them
side by side with an agreement score, so you can see who answers best on your data.

**Digest schedule**: Settings → Digest — pick the hour and frequency (daily /
every 2–3 days / weekly). "Run digest now" re-digests today manually (not
needed; it costs one AI call).

**More Settings switches**: "Apple on-device first" (default — free/private)
vs "always use my engine" for max quality on every question; form field
detection on/off; digest notification; **Report a bug** opens a prefilled
GitHub issue (nothing from your history is attached — only what you type).

**Onboarding** (first launch) now asks for your main browser and triggers the
one-time macOS automation consent for it right there.

### Pause capture
- **Cmd+Option+P** — global pause/resume toggle (works anywhere)
- Menu bar → **Pause** button (icon switches to the pause badge)
- `rewisp pause` / `rewisp resume` in terminal

### Saw something you want forgotten?
Menu bar → **Forget 10 min** — deletes everything captured in the last 10 minutes.

### The Vault (your personal info)
Main window → **Vault** tab: drag files in, delete with the trash button, or
**Add note** to type something directly (saved as markdown). Formats: `.md` `.txt`
`.pdf` `.docx`. **Never put passwords, SSN, or card numbers in it** — Rewisp
refuses files that look like they contain credentials and tells you why.
`rewisp-vault` in a terminal still opens the folder directly.

Vault beats screen history: if they conflict, the Vault answer wins.

The Vault tab is **locked behind Touch ID** (or your login password) — it holds
your most sensitive facts, so opening it prompts for authentication each visit.
If your Mac has no biometric or password enrolled, the Vault opens normally.

### Memory (what Rewisp learns about you)
Main window → **Memory** tab: approve ✓ or delete ✕ pending facts the digest
proposed. Confirmed facts are used as context in every answer. The file behind it
is `~/Rewisp/memory.md` — plain markdown, yours to edit. Rewisp never confirms
anything on its own.

---

## What happens automatically

| When | What |
|---|---|
| You switch apps / change URL / stop scrolling | Screen captured → OCR'd → text stored → image discarded (never written to disk) |
| Screen unchanged but you keep reading | Heartbeat capture every ~60s (dedupe drops identical screens) |
| 5 min without input, screen locked | Capture stops |
| Messages, WhatsApp, banking sites, password apps frontmost | Capture fully paused (kill list) |
| 9:00 PM daily | **Digest** — the one automated Claude call: daily summary, loose threads, memory proposals. Mac asleep at 9? Runs on wake. |
| Daily | Retention: captures + chats older than ~6 months deleted; summaries kept forever |
| Login / reboot | Daemon + menu bar app start automatically |

### Kill list
Defaults: Messages, WhatsApp, password managers, ~20 banking/finance domains,
private/incognito windows. Defaults can't be removed. Add your own apps/domains in
the main window → **Settings** tab — changes apply live, no restart needed.

### Browsers
URL capture + the banking-site kill list work in **Dia, Chrome, Arc, Edge,
Brave, Vivaldi, Opera** (Chromium AppleScript) and **Safari**. Incognito is
detected directly in Chromium browsers (capture fully pauses); Safari private
windows rely on window-title keywords. **Firefox**: title-only — no URL
trigger and no URL kill list there. First use of each browser triggers one
macOS automation consent prompt.

### Form assist
Focused a form field, forgot the value? Hit ⌘⇧Space — the panel notices the
field behind it ("You were in a 'Email' field") and offers **Find mine**, which
looks it up in your Vault/history with a Copy button. Rewisp never types into
or submits forms — you paste it yourself.

---

## Terminal reference

```
rewisp ask "what was that github repo from tuesday"
rewisp search <keyword>       fast FTS search, no AI call
rewisp status                 capture count, DB size, paused?
rewisp pause | resume
rewisp digest                 run tonight's digest early (once/day guard; --force to redo)
rewisp memory                 show confirmed + pending memory
rewisp vault | rewisp-vault   open vault folder + reindex
```

## Files & places

| Path | What |
|---|---|
| `~/Rewisp/rewisp.db` | all captured text (SQLite, local only) |
| `~/Rewisp/memory.md` | learned memory — yours to edit |
| `~/Rewisp/vault/` | your personal info files |
| `~/Rewisp/.api_token` | secret the app uses to talk to the daemon (don't share) |
| `~/Rewisp/daemon.log` | live activity log (`tail -f` it) |
| `~/Rewisp/digest_log.jsonl` | digest call history (one/day, watch usage here) |
| `~/Code/Rewisp/` | source code + docs |

## If something's off

- **Menu bar says daemon isn't running** → `launchctl kickstart -k gui/501/com.rewisp.daemon`
- **Orange permission card** → System Settings → Privacy & Security → Screen Recording → enable **Python**
- **Ask says "sign in to Claude Code"** → run `claude` in a terminal, sign in
- **Answers feel stale/wrong** → check the cited source timestamps; Rewisp only
  answers from what it saw — "not found in your memory" means it truly wasn't on screen
- **Hotkeys dead** → menu bar app running? `open /Applications/Rewisp.app`
- **"unauthorized" from the API** → app and daemon disagree on the token; restart both
  (`launchctl kickstart -k gui/501/com.rewisp.daemon`, then relaunch Rewisp.app)

## Privacy model, one paragraph

Screenshots never touch disk — OCR happens in memory, image released immediately.
Only text is stored, locally, in SQLite (`~/Rewisp`, readable only by you). Kill-list
apps are never captured at all. Quick answers are generated on-device. Nothing leaves
the Mac except question context sent to Claude when the on-device model can't answer,
and one digest call at 9 PM. Raw capture text auto-deletes after ~6 months. No API
keys, no telemetry, no cloud storage.
