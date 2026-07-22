# Rewisp — User Manual

Your Mac remembers everything you see. Every glimpse of your screen becomes a
**wisp** — text only, stored on this Mac. Ask anything later and Rewisp *revisits*
those wisps to answer. Quick answers run on Apple's on-device model ($0, nothing
leaves the Mac); hard questions and the nightly digest use a stronger engine
(Claude / ChatGPT / free Gemini / Ollama — whichever you've set up, $0 extra).

---

## Your data is encrypted

The database is encrypted with SQLCipher (AES-256). You don't set this up and
there's nothing to remember: the key is generated on first run and kept in your
login Keychain, and Rewisp unlocks it automatically.

If you were using Rewisp before this, it converts your existing database the next
time it starts. That takes about a second, keeps a copy of the old file next to it
until everything checks out, and needs nothing from you.

What this protects: the file itself. Someone who takes the disk, restores a
backup, or copies `~/Rewisp` gets ciphertext.

What it doesn't: a program already running as you, which can read the same
Keychain entry. That's the honest limit of automatic unlocking, and the daemon
needs automatic unlocking to capture at all.

## Card numbers and SSNs are stripped (new in 0.27)

The kill list already pauses capture on banking sites, password managers and
private windows. As a backstop for the times a card number or SSN shows up on an
ordinary screen — an order confirmation, an email quoting a number — Rewisp
removes it before the row is ever stored. A card number (13–19 digits that pass
the Luhn checksum and start with a real card-network digit) or a dashed SSN is
replaced with `[card]` / `[ssn]`. The surrounding memory stays useful ("paid with
`[card]`"); the number is gone, from both the database and the search index.

It's deliberately cautious — it only removes numbers it can validate, so it won't
mangle an order id or a phone number. It runs on new captures; anything already
stored keeps what it had (still encrypted). On by default.

## A note on the Vault and Touch ID

The Vault tab is gated by Touch ID, and that is a UI gate: it stops someone
opening the tab on your unlocked Mac. It is **not** encryption. The files sit in
`~/Rewisp/vault/`, protected by the same thing as everything else — the folder is
locked to your account and FileVault covers the disk. Anything running as you can
read them without ever meeting the Touch ID prompt.

Worth being precise about, because "Touch ID locked" sounds like more than it is.

## Installing

Download **Rewisp.dmg** and drag Rewisp into Applications. Grant Screen Recording
to **Rewisp Backend** when Rewisp asks — it turns green by itself once you do.

**Opening it the first time.** macOS blocks apps it can't verify, and since
macOS 15 the old right-click → Open trick no longer works. Double-click Rewisp,
click **Done** on the warning, then open **System Settings → Privacy & Security**,
scroll to **Security**, and click **Open Anyway** next to the Rewisp line. That
button only appears after you've tried to open the app once.

**Drag it over before opening it.** If you open Rewisp straight from the disk image,
it will offer to move itself to Applications and reopen — take it. Rewisp's background
helper is launched by macOS from wherever the app sits, so a copy running off the disk
image stops working the moment you eject, and the screen permission you granted there
doesn't transfer.

That's the whole install. There is nothing to run in Terminal and no Python to
install — the app carries its own runtime and starts its background helper by
itself the first time you open it. Illustrated walkthrough: `site/install.html`.

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

### How fast an answer arrives

Rewisp answers on-device first — usually a couple of seconds, free, nothing
leaving the Mac. If that answer is enough, you're done.

If you want more, click **Think longer** underneath it. That sends the same
question to your stronger engine (Claude, ChatGPT, Gemini, whichever you've set
up) and replaces the answer when it arrives, typically in another ten seconds or
so. The on-device answer stays on screen while it works.

Previously Rewisp made that decision for you and threw the on-device answer away,
which meant waiting for both. If you'd always rather go straight to the strong
engine, turn off "Apple on-device first" in Settings → Answers.

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

The Vault tab prompts for Touch ID (or your login password) each visit. That is a
gate on the tab, not on the files — see the note at the top of this manual. If
your Mac has no biometric or password enrolled, the Vault opens normally.

### Memory (what Rewisp learns about you)
Main window → **Memory** tab: approve ✓ or delete ✕ pending facts the digest
proposed. Confirmed facts are used as context in every answer. The file behind it
is `~/Rewisp/memory.md` — plain markdown, yours to edit. Rewisp never confirms
anything on its own.

---

## Thinking features (new in 0.8)

Rewisp doesn't just store your screen — it reasons over it. These run locally
and free.

### Meaning-based search
Search understands meaning, not just keywords. Ask *"that article about burnout"*
and it finds the page that said **"exhaustion"** — no shared words needed. Every
wisp gets a local semantic fingerprint (model2vec, ~0.1 ms, no cloud); answers
fuse keyword + meaning ranking. If the embedder is offline it silently falls back
to keyword search.

Search is also **typo-proof** (new in 0.27): OCR sometimes misreads a word
(`client` → `cl1ent`), which used to make exact search miss it. A trigram index
matches on shared letter-chunks, so a clean search term still finds the mangled
copy. It only ever adds results, never removes the exact ones.

And when a search truly misses, you don't get a dead end: the answer includes
**"Closest moments in your memory"** — the three nearest things Rewisp did see,
with app and time — because half the time you just misremembered the wording.

### "What changed on this page?"
Because Rewisp stores every version of a page as text, it can diff them. On any
page you revisit, ⌘⇧Space → *"what changed on this page?"* or *"what's new here
since Tuesday?"* → it shows what was **added / changed / removed** (a **Delta**
badge marks these). Numbers that moved (a price, a grade) are called out. As of
0.27 it ignores OCR wobble — a line that merely read differently twice isn't
reported as a change, only a real edit is.

### Promises
Rewisp catches commitments off your screen — *"I'll send mavi the doc"*, *"email
manvi by end of today"*, *"call dona today"* — and pins them to **Today →
Promises** as little slips: what **you owe** and what you're **waiting on**. You
never type them. Tap ✓ to confirm, ✕ to dismiss; confirmed ones get a **Done**
button that crumples the slip away. Overdue slips glow red.

It only listens where *you* write: Notes, Mail, Slack, Discord, Gmail and the
like. AI chats, code editors, ads, and random web pages can't create promises —
so the list stays yours, not noise.

**Confirming a promise arms its reminder:** on the due day (and while overdue) a
small pill slides down from the menu bar with the full commitment — one reminder
per day, never spam. Pending slips you never confirmed stay silent.

**It reads deadlines the way you write them.** *"by EOD"*, *"end of the week"*,
*"next week"*, a weekday or a date — all resolve to a real due day, so the
reminder lands when it should.

**It knows the difference between a promise and a maybe.** *"I'll send it"* is a
promise; *"I'll try to"*, *"hope to"*, *"maybe later"* are not, and won't clutter
your list. Quoted replies and email signatures are ignored too — only the line
*you* actually wrote counts.

**Kept promises close themselves.** When you later write that you did it —
*"emailed Dana the report"* — Rewisp marks the slip **Done** for you, so nothing
nags after it's handled.

### Numbers over time
Any label+number Rewisp sees repeatedly — a weight, a grade, a price, tracked
hours — becomes a **series** on **Today → Tracked** with a sparkline, once it's
seen 3+ times with variance. Ask *"how has my weight moved?"* → current value,
change, and recent points, charted from your own screen. No integrations.
(Credential-shaped and menu-bar numbers are refused.)

### Precognition (guessed questions)
Summon ⌘⇧Space without typing and the suggestion chips are **guessed from what's
on your screen + your history** — a page you've seen before offers *"What changed
on this page?"*, a terminal error offers *"Have I seen this error before?"*.

### Memory that consolidates + strengthens
Each night Rewisp folds older wisps into **episodes** (short summaries of a
session), so long-term recall stays fast — see the layers in **Settings → Your
data → Memory layers** (raw wisps → episodes), with a **Consolidate now** button.
Wisps you actually ask about get **reinforced** (they rank higher and survive
longer). Fully local, no extra AI call.

### It learns how you forget
Every failed search and re-asked question is a documented forgetting event —
Rewisp fits **your own forgetting curve** per kind of fact (names, numbers,
links, dates, places) and shows it in **Settings → Your data → How you forget**:
five decay curves with "half-gone in ~N days" dots, drawn from your real slips.
Two things act on it automatically:
- **About to fade** — something you saw once and never revisited gets a single
  rescue mention in the nightly digest, timed right before it crosses your
  predicted forgetting cliff (the same trick that makes spaced repetition work).
- **Pinned** — the ~3rd time you look up the same stable fact (a wifi password,
  a door code, a link), Rewisp pins it: answered instantly, exactly, forever.
  Time-dependent questions ("what did I do yesterday") are never pinned.

### Proactive recall (off by default)
When the screen relates to something you saw before, Rewisp can slide a small
**nudge pill** down from the menu bar — hover it to expand into the memory, 👍/👎
to tune it. It's **off by default**; enable it in **Settings → Notifications →
Proactive nudges**, and use **Send test nudge** there to see it. Detection is
fully local; nudges never make a cloud call.

---

## What happens automatically

| When | What |
|---|---|
| You switch apps / change URL / stop scrolling | Screen captured → OCR'd → text stored → image discarded (never written to disk) |
| Screen unchanged but you keep reading | Heartbeat capture every ~60s (dedupe drops identical screens) |
| 5 min without input, screen locked | Capture stops |
| Messages, WhatsApp, banking sites, password apps frontmost | Capture fully paused (kill list) |
| Every capture | Commitments detected ("I'll send it Friday") → held as **Promises**; recurring label+numbers → **series**; a semantic fingerprint is stored for meaning-based search — all local |
| 9:00 PM daily | **Digest** — the one automated Claude call: daily summary, loose threads, memory proposals. Mac asleep at 9? Runs on wake. |
| Nightly | **Consolidation** — older wisps folded into episodes; wisps you've asked about reinforced. Local, no AI call. |
| Daily | Retention: captures + chats older than ~6 months deleted (reinforced wisps kept longer); summaries + episodes kept forever |
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

### Connect to AI agents (MCP)
Rewisp can hand its memory to **Claude Desktop, Claude Code, or any MCP client**
so an agent can search your screen history, diff pages, and read your promises
while it works. It's a dedicated section: **Settings → Connect agents**, with a
live status banner that turns green the moment an agent first queries.

Three ways to set it up (all in that section):
- **Claude Desktop** — click **Add to Claude Desktop**; Rewisp writes the config
  for you. Quit and reopen Claude Desktop and "rewisp" shows under its Connectors.
- **Claude Code** — copy the one-line `claude mcp add rewisp …` command into a terminal.
- **Other client** — copy the raw `mcpServers` JSON block into your client's config.

**Test it:** ask the agent *"What did I work on yesterday?"* or *"What have I
promised this week?"* — if it answers from your history, you're connected.

It exposes five read-only tools — `search_memory`, `get_context`,
`get_day_summary`, `get_promises`, `get_page_changes`. It is **read-only** (no
tool can write or delete), **local** (stdio — no network listener), and it
**never calls a cloud engine**, so an outside agent can never spend your
subscriptions. Your **Vault stays private** unless you flip "Also expose the
Vault" in that section.

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
rewisp embed-backfill         compute semantic fingerprints for old wisps
rewisp dream                  consolidate aged wisps into episodes now
rewisp mcp                    MCP server for AI agents (read-only, stdio)
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
- **Orange permission card / capture stopped after an update** → click **Allow
  screen access** on the card. Do not just toggle the existing switch in System
  Settings: after an update that row is stale (it points at the previous build),
  so flipping it changes nothing. Rewisp removes the stale entry for you and
  reopens the right page, then picks up the new grant by itself.

  Why it happens: macOS identifies apps by an exact code signature and Rewisp
  isn't signed with a paid Apple certificate yet, so an updated build looks like
  a different app and the old permission is dropped. Nothing is lost when it
  happens.

- **"Could not connect to the server"** → the background helper isn't running. Click
  **Finish setup** in the search panel; it re-provisions the launchd agents. This is
  self-healing since v0.12 (the app carries its own Python), so it should be rare.
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
