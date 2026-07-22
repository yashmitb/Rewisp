# Security notes

Audited 2026-07-08. Threat model: Rewisp stores everything the user sees on screen as text — the database is the most sensitive file on the machine. Adversaries considered: other local processes/users, malicious web pages, exfiltration via the AI calls, and plain operator error.

## Data at rest

**Encrypted** since v0.23.0: SQLCipher, AES-256, 256,000 KDF iterations. The WAL
and shared-memory sidecars carry no plaintext either — verified specifically,
since encrypting only the main file would be theatre.

The key is 256 bits from `secrets`, stored in the login Keychain and read via
`/usr/bin/security`. That indirection is deliberate: Keychain ACLs bind to the
calling binary's code identity, Rewisp is ad-hoc signed, and its identity changes
every release — binding the item to our own binary would produce a prompt or a
denial after every update, exactly the failure that made Screen Recording so
painful. `security` is Apple-signed and stable.

**What this defends against:** a stolen or imaged disk, a Time Machine or other
backup, `~/Rewisp` copied or synced anywhere, and any other account on the Mac.

**What it does not:** a process already running as your user. It can read the same
Keychain item, or simply call the local API. Touch ID gating would not close this
either — the capture daemon must hold the key continuously to work at all, so the
only thing gating would add is a gap in the timeline after every reboot.

Migration from a plaintext database is automatic and refuses to lose data: it
exports to a new file, verifies row counts per table *and* runs a real FTS query
against the copy, and only then swaps. The original is kept as
`rewisp.plaintext-backup`. Any failure leaves the plaintext file byte-identical.

## PII redaction (since v0.27.0)

A content-level backstop beneath the kill list. Before a capture is stored or
embedded, `redact.scrub_pii` removes validated card numbers (13–19 digits passing
the Luhn checksum and starting with a card-network digit 3/4/5/6) and dashed SSNs
in SSA-issued ranges, replacing them with `[card]` / `[ssn]`. Applied at two
points: in the daemon before the embedding is computed, and in `insert_capture`,
the single choke point every ingestion path shares — so neither the row, the
embedding, nor the derived FTS/trigram indexes hold the number.

Precision-first on purpose: it only redacts what it can validate, so it will miss
a card glued to adjacent OCR text and will not touch an order id or phone number.
It is a reduction of exposure, not a guarantee — the kill list, on-device
processing, and encryption at rest remain the primary defences. On by default
(`REDACT_PII`).

**Scope:** forward-looking only. Rows captured before v0.27.0 keep whatever PII
their `ocr_text` already held (encrypted at rest); the feature does not rewrite
history. A one-time re-redaction of existing rows is a possible future addition.

## Historical: plaintext at rest (before v0.23.0)

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

**`pinned` — closed in v0.23.1.** Facts you look up repeatedly are pinned and
kept forever, which made them the one place a forgotten wisp could survive
indefinitely, as a deterministic answer no less. Pins now record which wisps
produced them, and forgetting any source removes the pin, exactly as episodes
behave. Pins created before v0.23.1 have no provenance recorded and are left
alone — silently deleting facts someone relies on, to close a gap they may not
have, is the worse trade.

## Accepted risks

- OCR text from non-kill-listed apps can still contain sensitive content the user had on screen (mitigations: kill list, pause hotkey, forget button, 700 perms).
- The app is ad-hoc code-signed (no Developer ID); Gatekeeper on other machines requires right-click → Open. Auto-update therefore notifies + downloads rather than silently replacing the binary.
- launchd runs the daemon as the login user; anyone with the user's session already has the same access the daemon has.
