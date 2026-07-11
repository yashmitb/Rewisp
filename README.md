# Rewisp

**An ambient memory for your Mac.** Every glimpse of your screen becomes a **wisp** — its text remembered, never the pixels. Ask anything later and Rewisp *revisits* those wisps to answer — instantly, from the menu bar or a Spotlight-style hotkey.

[**⬇ Download for Mac**](https://github.com/yashmitb/Rewisp/releases/latest/download/Rewisp.dmg) · macOS 15+ · Apple Silicon

> "What was due on July 12th?" · "What was that video I watched last night?" · "What's my advisor's email?"

<p align="center">
  <img src="docs/img/panel.png" width="640" alt="⌘⇧Space search panel answering from screen history with the Apple on-device model">
</p>

Answers come from Apple's on-device model in a few seconds — the badge shows which engine replied. When the on-device model isn't sure, Rewisp escalates to a stronger engine: **Claude Pro → ChatGPT Plus → free Gemini → local Ollama** (whichever you've set up; no paid API keys, ever). Personal facts (your email, IDs, addresses) come straight out of the Vault, deterministically, with a Copy button — and the Vault is gated behind Touch ID.

<p align="center">
  <img src="docs/img/settings.png" width="720" alt="Main window: engine chain, digest schedule, notifications">
</p>

## How it works

```
┌─ triggers ─────────────┐   ┌────────────┐   ┌─────────────┐
│ app switch · new URL   │ → │ screenshot │ → │  Vision OCR │ → SQLite FTS5
│ scroll settle · 60s HB │   │ (in-memory │   │  (on-device)│    (text only)
└────────────────────────┘   │  only)     │   └─────────────┘
                             └────────────┘
Ask (⌘⇧Space) → FTS retrieval → Apple on-device model (free, private)
                                └→ Claude / ChatGPT / free Gemini / Ollama for hard questions
Nightly Digest (9 PM) → one Claude call → recap · loose threads · memory
```

- **Screenshots are never written to disk.** Each capture is OCR'd in memory and released; only the recognized text is stored.
- **Everything stays local** — SQLite database in `~/Rewisp`, on-device OCR, on-device answering via Apple's Foundation Models. The only thing that ever leaves the machine is the prompt for Claude-answered questions and the once-daily Digest (via your Claude subscription — never an API key).
- **Kill list**: Messages, WhatsApp, password managers, banking sites, and private browser windows fully pause capture. Not filtered — *paused*: zero rows.
- **Vault**: drop your resume / addresses / standard answers in, and Rewisp treats them as trusted truth. Files that look like they contain credentials are refused.

## Pieces

| Piece | What it is |
|---|---|
| `rewisp/` | Python daemon — capture, OCR, storage, retrieval, localhost API (127.0.0.1, token-gated) |
| `ui/` | Native SwiftUI menu bar app + ⌘⇧Space search panel + main window (Chat, Vault, Memory, Settings) |
| `docs/` | Brief, manual, progress log, security notes |
| `scripts/` | DMG packaging + installer |
| `site/` | Landing page |

## Install (from source)

Requires macOS 15+ (on-device answers need macOS 26), Python 3.13 with `pyobjc`, and [Claude Code](https://claude.com/claude-code) signed in for Digest/fallback answers.

```sh
pip3 install pyobjc
python3 -m rewisp daemon          # grant Screen Recording when prompted
cd ui && ./build.sh --install     # builds + installs /Applications/Rewisp.app
```

`scripts/install.sh` sets up launchd agents so the daemon runs on login and the Digest fires at 9 PM. `scripts/make_dmg.sh` builds a distributable DMG.

## Privacy principles

1. Image in memory only — OCR, then gone.
2. Text only, local only, `~/Rewisp`, `chmod 700`.
3. Kill list is absolute.
4. Credentials are never stored — detection refuses them at the door.
5. At most one automated AI call per day (the Digest). Everything else is user-triggered or on-device.
6. Forget button: delete the last 10 minutes any time.

## License

MIT
