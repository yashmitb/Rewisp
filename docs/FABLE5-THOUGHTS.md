# Fable 5 Thoughts

*A full read of the app — every doc, every Python module, every Swift file — as of v0.8.1 (2026-07-14). Three parts: what needs fixing, what could be better, and two new features grounded in memory science.*

*Research note: grounded in the established memory-science literature — Ebbinghaus's forgetting curve, Tulving's encoding specificity, the Zeigarnik effect, Einstein & McDaniel's prospective-memory work, Gloria Mark's task-interruption studies, Johnson's source-monitoring framework. The two load-bearing claims were verified against live sources (see Sources at the bottom): Mark's ~23-minute interruption-recovery finding, and the intention-behavior confusion behind "did I lock the door?" checking loops — including the finding that re-checking creates* more *doubt, not less, which is exactly why proof beats re-checking.*

---

## Part 1 — Things that need to be fixed

Ordered by how much they matter.

### 1.1 Privacy invariant gap: forget/retention don't purge everything (real bug)
`todo.md`'s cross-cutting note is explicit: *"Forget last 10 min must also purge embeddings, deltas, promises, series rows, and episode references."* Today `db.delete_captures` cascades to **promises** (and embeddings live on the row, so they go free), but:
- **`series` rows** carry `wisp_id` and are not purged — a forgotten wisp's number stays charted.
- **`episodes.wisp_ids_json`** can reference deleted wisps (dangling ids), and an episode's *summary text* survives even when its source wisps were forgotten. If a user hits "Forget 10 min," extractive lines from those minutes can still sit inside an episode built later that night — or already built by `dream` catch-up.
- **`queries`** stores every question + embedding forever (no retention at all). Your questions are also memory.

**Fix:** extend the `delete_captures` choke point to (a) delete `series` rows by wisp_id, (b) rebuild or scrub episodes whose `wisp_ids_json` intersects the deleted set, and (c) add a retention window for `queries`. This is the kind of gap that undermines the "private by construction" promise if anyone ever audits it.

### 1.2 Deadline dates can be off by one day (timezone bug)
`promises._extract_due` returns `str(d)[:10]` from NSDataDetector — that's a **UTC** date. A promise captured at 6 PM PT saying "tomorrow" resolves against a UTC clock already on the next day; "due today" chips and the overdue red glow can be a day wrong in the evening. Same class of bug the digest already hit once (monotonic-vs-wall-clock). Convert to the local calendar day before storing.

### 1.3 Test nudges eat the real nudge budget
`nudge_count_today` counts all rows created in 24 h, and `/nudge/test` inserts real rows. Pressing "Send test nudge" three times silences genuine Déjà Vu nudges for the day. Exempt `type='test'` (or topic_key prefix `test:`) from the cap.

### 1.4 Digest may bypass the engine chain
`digest.py` imports `from .ask import call_claude` directly. The settings UI implies the digest respects your chosen engine/chain; if Claude's session limit is hit at 9 PM (it happened live on 07-08), the digest fails instead of falling through to Gemini/Ollama. Route the digest through `call_llm` like everything else.

### 1.5 First-run offline = semantic search silently off
`embed._load` downloads `potion-retrieval-32M` from Hugging Face on first use. A user who installs the DMG on a plane gets keyword-only search with no explanation, and the download is attempted inside the long-lived daemon. Bundle the model files in the DMG (they're small) or fetch during `install.sh` with a visible progress line.

### 1.6 Episode titles are OCR garble
Real output seen in testing: `"Antigravity IDE: CO meta meta = {"answer": fact["answer"]…"`. Extractive titles from code editors and busy pages read as noise. Cheap fix: title = `top_app + " — " + page domain/title` when the salient line fails a "looks like prose" check. Nicer fix: fold episode titling into the one nightly cloud call the digest already makes (zero extra calls).

### 1.7 Reinforcement can be gamed by the system itself
`dejavu.find_recall` bumps `recall_count` on every *surfaced* match — including matches the user never saw (nudges disabled path is gated, but `/nudge/test` and future callers aren't). Reinforcement should mean *the human used this memory*, not *the machine touched it*. Move `bump_recall` to delivered/interacted events only.

---

## Part 2 — Things that could be better

### Architecture / scaling
- **Every vector search re-reads the whole embedding corpus from SQLite** (~40 MB at 20k wisps) and rebuilds a numpy matrix — per query, per capture (Déjà Vu), per precog summon. Fine today; at 100k+ wisps (reinforcement exemptions make the corpus grow past 6 months) it's the first thing that will feel slow. Cache the matrix in the daemon process and invalidate on insert/delete; that's a 20-line fix that removes the ceiling.
- **The 9 PM job is now five jobs** (digest, embed backfill, page_key backfill, dream, retention) with no per-stage timing or failure isolation — one stage throwing shouldn't starve the rest. `todo.md` already calls for a mini-pipeline with per-stage logs; it's time.
- **The daemon capture path does a lot per wisp now** (OCR, embed, promises regex, numbers regex, Déjà Vu matmul). Still fast, but there's no timing telemetry. One log line per capture with stage timings would catch a regression before the user feels their fans.

### Product / UX
- **"Continue in chat" never shipped.** The original brief (§4.1/4.2) promised panel → threaded chat continuity. Today a panel answer is a dead end; the Chat tab doesn't know about it beyond the log line. This is the most-used surface in the app — one button that opens Chat pre-loaded with the exchange would complete the loop.
- **Vault Touch ID on every visit** is the right paranoia with the wrong grace period. A 5-minute re-auth window (like sudo) keeps the protection and kills the eye-roll.
- **Recency isn't a retrieval signal.** RRF fuses keyword + meaning + reinforcement, but a wisp from 20 minutes ago and one from 4 months ago rank the same on those axes. Most questions are about *recent* life; add a time-decay as a fourth RRF signal.
- **Delta's ignore-list has no UI.** `delta_ignore.json` is hot-reloadable but invisible — a "this diff is churn" thumbs-down on a delta answer could append a pattern automatically.
- **Promises lack snooze/edit.** Real promises slip. A right-click → "push to Monday" on a slip is 30 minutes of work and doubles daily usefulness. The auto-done heuristic (later wisp says "sent it") is spec'd in todo.md and worth shipping.
- **Numbers doesn't normalize units** ("lbs" vs "pounds" vs "lb" split into three series) and a series never expires even when the page is gone.
- **Precognition's tap-through rate** was the whole "done when" criterion (>20%) — it's logged (`was_tapped`) but never reported anywhere. Add the number to Settings → Your data so tuning is possible.
- **Landing page hero is stale to the product.** v0.8's Delta ("Ask any page what changed") was planned as *the* headline and is still below the fold. The three GIF-able moments (delta, pill, crumple) remain unrecorded.

### Distribution / quality
- **Ad-hoc signing** means every new Mac needs right-click-Open, and auto-update can't replace the binary silently. $99/yr Developer ID + notarization is the single biggest "feels like a real product" purchase available.
- **No Swift-side tests.** The `.task`-on-EmptyView bug (promises card never loading) shipped and was found by hand; pytest can't catch that class. Even 5 XCTest cases around decode + view-model logic would have.
- **RAM budget unverified.** The v1 definition of done says <300 MB all day; numpy + model2vec + pyobjc in the daemon deserves one real measurement logged in PROGRESS.md.

---

## Part 3 — Two new features (the unique ones)

The research lens: surveys of everyday memory failures consistently rank these at the top — (1) *prospective* failures ("I was going to do something — what?"), (2) *source-monitoring* failures ("did I actually do it, or just think about it?"), (3) losing your place after interruption (the "doorway effect" — context switches purge working memory), and (4) names/what-was-that-thing. Rewisp already attacks (1) with Promises and (4) with search. The two features below attack (2) and (3) — the two nobody in this space has touched, and both are *deterministic, local, free* — pure Rewisp architecture.

---

### Feature A — **"Where was I?"** (resumption memory / the anti-doorway-effect)

**The science.** Gloria Mark's interruption research: after a context switch it takes ~23 minutes to fully resume a task, and the single biggest accelerator is a *resumption cue* — being shown the exact state you left. Radvansky's "doorway effect": crossing a context boundary (a doorway — or an app switch, a lunch break, a night's sleep) flushes the active intention from working memory. The information isn't gone; the *pointer* to it is. People don't need a summary of what they did — they need their pointer back.

**The feature.** One question, answered instantly, anywhere: **"Where was I?"**

- ⌘⇧Space → the panel's first chip is **"Where was I?"** whenever you've just returned to an app/project after a gap (>30 min). One tap → a *resumption card*, built deterministically from the last wisps of that context before the gap:
  - the exact page/file you were on (page_key + title),
  - the last distinct thing on screen (cleaned salient lines — the sentence you were mid-writing, the field you were mid-filling, the error you were mid-reading),
  - what you'd just searched/asked,
  - one tap to re-open the URL.
- **Morning mode:** first summon of the day answers "Yesterday you stopped mid-X" — not a digest of the day, but the *cliff edge* you walked away from.
- **Interruption mode (the magic):** the daemon already sees every app switch. When you bounce Slack → back to Xcode after 10+ minutes away, a quiet one-line pill: *"You were editing ask.py — build_context, line ~240."* No model, no cloud: it's the last wisp of that page_key, cleaned.

**Why it's unique:** Every memory tool answers "what did I see?" Nothing on the market answers **"what was I *doing*?"** — resumption, not recall. Video tools can't do it cheaply (they'd have to re-watch footage); Rewisp has the text of the exact moment, pre-indexed by page identity, already deduplicated. It also compounds with what's built: promises are intentions *stated*, "Where was I?" is intentions *interrupted*.

**Build sketch (~2 days):** `resume.py` — `last_context_before_gap(conn, app|page_key, gap_min=30)` pulling the pre-gap wisps for the frontmost app; reuse `dejavu.clean_snippet` + `dream._salient_lines` for the card body; a precog template chip ("Where was I?") gated on gap detection; nudge-pill delivery for interruption mode (off by default, like Déjà Vu). All deterministic.

---

### Feature B — **"Did I?"** (the proof log / verification memory)

**The science.** Source-monitoring failures (Johnson): the brain is bad at distinguishing *did it* from *intended to do it* from *imagined doing it*. This is why people re-open Gmail to check a sent email, re-open the banking app to confirm rent went through, re-check that a form was actually submitted — and why "did I lock the door?" is the canonical everyday memory complaint. The checking loop is pure wasted time and low-grade anxiety, and it happens *precisely because the confirmation moment was seen once and never encoded*.

**The feature.** Rewisp watched you do it — so make it the **evidence locker**.

- **Passive detection:** confirmation-shaped moments are extremely regular on screen — "Message sent", "Order #… confirmed", "Payment successful", "Quiz submitted", "Your booking is confirmed", "Application received", "Pushed to main". A cheap local classifier (regex families + on-page context, same style as Promises) tags these wisps as **receipts** at capture time: `{kind: sent|paid|submitted|booked|ordered, counterparty, amount?, ts, wisp_id}`.
- **The killer interaction:** ask **"did I…?"** and get a deterministic answer with *proof*:
  - *"Did I submit the Calc quiz?"* → **"Yes — you saw 'Quiz submitted' Sunday 11:52 PM."** (source wisp attached)
  - *"Did I pay rent this month?"* → **"Yes — Zelle confirmation, Jul 1, $1,450."**
  - *"Did I reply to Dana?"* → **"No record of a sent reply — you last had her email open Thursday."** (an honest *no* is half the value)
- **Receipts tab/card:** a quiet reverse-chronological ledger of everything that *definitely happened* — filterable (payments / sent / submitted). Six months later, "did I cancel that subscription?" has a receipt.
- **Closes the loop with Promises:** a receipt that semantically matches an open promise auto-proposes completion ("You promised to email Manvi — a 'sent' receipt to Manvi appeared 2:14 PM. Mark done?"). That's the auto-done heuristic from todo.md, but grounded in evidence instead of guesswork.

**Why it's unique:** To-do apps track intentions. Banks/inboxes each hold their own fragment. **Nothing holds cross-app proof of completion**, because nothing else sees the confirmation screens. It converts Rewisp's most mundane captures — the confirmation flashes everyone instantly forgets — into the single highest-trust answers the app can give ("deterministic, with the screenshot-text as evidence"). And it's the perfect complement to Promises: one tracks *what you owe*, the other proves *what you've done*.

**Build sketch (~2–3 days):** `receipts.py` detector (regex families per kind, credential/kill-list guards as always) + `receipts` table (cascade into `delete_captures`); a "did I / have I" intent route in `ask.py` answering deterministically like Vault facts (searching receipts first, falling back to wisp search with an honest "no record"); Today card + promise-matching via the embeddings already computed.

---

### Why these two, together

They're the two halves of the intention lifecycle Rewisp doesn't yet close: **"Where was I?"** recovers intentions that got *interrupted*; **"Did I?"** verifies intentions that got *completed*. Promises already holds intentions that got *stated*. With all three, Rewisp covers the full arc of a human intention — stated → interrupted → resumed → done → proven — entirely from passively watched text, entirely on-device, at zero marginal cost. No competitor is even framing the problem this way.

---

## Sources

- [It takes 23 minutes to recover after an interruption](https://addyo.substack.com/p/it-takes-23-mins-to-recover-after) — Gloria Mark's UC Irvine finding (~23 min to return to a task at focus; ~2 intervening tasks before resuming).
- [EEG correlates of cognitive dynamics in task resumption after interruptions](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11851001/) — resumption lag and how available context at resumption changes recovery.
- [Source-monitoring error](https://grokipedia.com/page/Source-monitoring_error) — intention-behavior confusion: mistaking a *planned* action for a *completed* one ("did I lock the door, or only imagine it?").
- [The checking trap](https://www.ocdanxietycenters.com/south-jordan-utah/the-checking-trap-when-did-i-lock-the-door-controls-your-life/) — re-checking creates more doubt, not less; evidence beats repetition.
