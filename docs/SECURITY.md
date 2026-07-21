# Security notes

Audited 2026-07-08. Threat model: Rewisp stores everything the user sees on screen as text — the database is the most sensitive file on the machine. Adversaries considered: other local processes/users, malicious web pages, exfiltration via the AI calls, and plain operator error.

## Data at rest

- `~/Rewisp/` is `chmod 700` (enforced on every daemon start).
- Screenshots are **never written to disk** — `CGDisplayCreateImage` → Vision OCR in memory → released. Only text rows exist.
- Captures/chats auto-delete after ~6 months (`RETENTION_DAYS`).
- Vault ingest refuses files matching credential patterns (SSN, card numbers, `password:`, `api_key:`) — refusal happens before anything is indexed.
- "Forget last 10 minutes" and pause (⌘⌥P / menu bar) for operator error.

## Localhost API (127.0.0.1:43117)

- Binds loopback only; nothing listens on external interfaces.
- **Token-gated**: every request requires `X-Rewisp-Token` matching `~/Rewisp/.api_token` (created `0600`). Without this, any local process — including a malicious web page doing `fetch("http://127.0.0.1:43117/...")` — could read the screen history. Browsers can't read the token file, and the comparison is constant-time (`hmac.compare_digest`).
- Request bodies capped at 1 MB; JSON parse failures return empty.
- `/vault/delete` guards path traversal: name must resolve to a direct child of the vault dir, no `/`, no leading dot.
- `/vault/note` sanitizes filenames to `[alnum -_]`, max 60 chars.

## Injection surfaces

- All SQL is parameterized. FTS5 query terms are individually quoted.
- No `shell=True` anywhere; subprocess calls (`claude`, `textutil`, `osascript`) use list args with constant scripts.
- AppleScript sent to Dia is a fixed string — no user input interpolated.

## AI calls

- `ANTHROPIC_API_KEY` set in the environment → the code **refuses to run the call** (would silently bill the API instead of the subscription).
- Quick answers run on Apple's on-device Foundation Model — nothing leaves the machine.
- Claude receives only: retrieval snippets for the asked question (interactive) or the day's compressed text (Digest, once per day). No images, no raw database.
- Prompt injection: screen text is untrusted input to the model. The system rules pin answers to the provided context; worst case is a wrong answer displayed to the user — the model has no tools and no write path.

## What "forget" actually removes

`db.delete_captures()` is the single choke point for forgetting: the 10-minute
button, kill-list purges, and retention all route through it. It deletes the
capture and every table derived from it — promises, series, episodes (the whole
episode, if a forgotten wisp fed one), the FTS row, and the embedding.

**`nudges` was missing from that list until v0.18.6.** A nudge quotes its source
wisp verbatim in its body, so forgetting a moment left a pill that repeated the
forgotten text back at you. Fixed, with a regression test.

**Known gap: `pinned`.** Facts you look up repeatedly are pinned and kept
forever, deliberately. A pinned row stores the question and the answer but no
reference to the wisps the answer came from, so forgetting those wisps cannot
remove it. In practice pinned answers are short factual values you asked for
several times, not passages of screen text, but it is a real gap and worth
knowing: review Settings → Your data if you have pinned something you would
rather Rewisp did not keep.

## Accepted risks

- OCR text from non-kill-listed apps can still contain sensitive content the user had on screen (mitigations: kill list, pause hotkey, forget button, 700 perms).
- The app is ad-hoc code-signed (no Developer ID); Gatekeeper on other machines requires right-click → Open. Auto-update therefore notifies + downloads rather than silently replacing the binary.
- launchd runs the daemon as the login user; anyone with the user's session already has the same access the daemon has.
