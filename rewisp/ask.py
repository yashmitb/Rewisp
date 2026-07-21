"""Ask pipeline: local time parse -> FTS retrieval -> one Claude call (Claude Code
subscription, never an API key) -> answer with sources -> saved to chats."""

import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import config, db, timeparse


def _fallback_cli_paths(name: str) -> tuple[Path, ...]:
    """CLI locations a GUI LaunchAgent cannot see through its minimal PATH."""
    home = Path.home()
    paths = [
        home / ".local" / "bin" / name,
        home / ".npm-global" / "bin" / name,
        Path("/opt/homebrew/bin") / name,
        Path("/usr/local/bin") / name,
    ]
    if name == "codex":
        paths[:0] = [
            Path("/Applications/ChatGPT.app/Contents/Resources/codex"),
            home / "Applications" / "ChatGPT.app" / "Contents" / "Resources" / "codex",
        ]
    return tuple(paths)


def cli_path(name: str) -> str | None:
    """Resolve a subscription CLI consistently for detection and invocation."""
    if found := shutil.which(name):
        return found
    for candidate in _fallback_cli_paths(name):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None

STOPWORDS = {
    "a", "an", "the", "i", "me", "my", "was", "is", "are", "were", "what", "which",
    "that", "this", "it", "of", "to", "in", "on", "at", "for", "from", "and", "or",
    "did", "do", "does", "have", "had", "has", "with", "about", "you", "can", "get",
    "find", "show", "tell", "there", "where", "when", "who", "how", "why", "right",
    "before", "after", "during", "some", "any", "again", "saw", "see", "looked",
    "looking", "open", "opened", "remember", "up", "past", "by",
}

SYSTEM_RULES = """You are Rewisp, answering questions about the user's own screen history.

Rules, in order of importance:
1. Answer ONLY from the context below. Never use outside knowledge, never guess.
2. If the answer is not clearly present, put EXACTLY "Not found in your memory."
   in ANSWER and stop. A wrong answer is far worse than admitting you don't know.
3. When several captures could answer, prefer the MOST RECENT one (highest #id / latest TIME).
4. Quote exact values (names, numbers, links, IDs) verbatim from the context — do not paraphrase them.
5. Timestamps in context are UTC; the user's local offset is given. Convert every TIME you output to local.
6. Vault entries are user-provided truth — if Vault and screen text conflict, Vault wins.

Answer quality:
- Be COMPLETE and SPECIFIC. Name the actual things — projects, files, sites, people,
  tasks, numbers. Never vague ("you did some work") when the context has specifics.
- For "what did I do / work on / happen" questions, cover the main threads, not just
  one. Give as many sentences as the answer genuinely needs; don't cut it short.
- For a specific fact (a name, number, link), give it directly and exactly.

ANSWER formatting (people scan, they don't read walls of text):
- Short answer (≤2 sentences): just write it, no structure.
- Longer answer: KEEP EVERY FACT — the structure re-arranges the full content,
  it never shortens it. Format:
  · line 1 = ONE sentence stating the overall answer (the lead).
  · blank line, then ALL the substance as bullets — one per thread/event:
    "- **Short topic** — the full detail for that thread, every specific fact,
    name, number, quote, and time that belongs to it. 1–4 sentences each."
  · bold key names, numbers, and times inline (e.g. **$36.04**, **5:00 PM**).
  · a long thread gets multiple bullets rather than one long paragraph.
- DETAIL is only for tangents (unresolved items, follow-ups) — never move the
  main content there. The complete detailed answer lives in ANSWER.

Respond in EXACTLY this format (omit a line entirely if it does not apply):
ANSWER: <the direct, complete answer — as long as the question needs, no citations here>
DETAIL: <any extra supporting findings worth knowing>
SOURCE: <where it was seen: app / site / file, human-readable>
TIME: <when it was seen, local time, e.g. "Today 4:13 PM" or "Mon Jul 6, 9:02 PM">
COPY: <if the question asked for a specific fact/value (name, ID, address, email,
link, number): the exact bare value alone, nothing else>"""


# Small on-device models (~3B) follow short, blunt, rule-led instructions. NOTE:
# a concrete worked example makes this model regurgitate the example's fake facts
# as if they were real (it can't tell sample from data), so we describe the format
# abstractly and lean hard on the anti-invention rule instead. Tuned for Apple
# Foundation Models.
COMPACT_SYSTEM_RULES = """You answer questions about the user's own screen history using ONLY the CONTEXT below.

RULES:
1. Write in your OWN plain English words. Your answer must never begin with "[" or
   with a URL. Never paste a raw context line, a capture id like [#2696], a section
   header like [summary ...], or a full web link. Rephrase every fact as a normal
   sentence (for a website: name the site and what was done; for a search: say what
   was searched for).
2. Use ONLY facts found in the CONTEXT. Never use outside knowledge and never invent
   names, apps, files, sites, numbers, or events. Only mention a website or app if it
   actually appears in the CONTEXT for the time asked about.
3. If the CONTEXT does not clearly contain the answer, reply with exactly:
   ANSWER: Not found in your memory.
   Do not guess. Do not fill in a plausible-sounding answer.
4. "Today" and "now" mean the MOST RECENT date in the CONTEXT. Prefer recent
   captures; ignore older ones that don't fit the question's time.
5. Scan the whole context. If it clearly shows several DIFFERENT activities from
   the time asked about — e.g. work in one app and entertainment in another — name
   each as its own list item. But include ONLY activities that actually appear for
   that time; do not pad with unrelated, old, or one-off captures.
6. Be specific: name the exact apps, files, sites, people, shows, episodes,
   versions, and numbers from the CONTEXT.
7. If your answer is longer than two sentences, format it for scanning:
   first a single short sentence saying the overall answer, then a blank line,
   then one line per activity starting with "- " followed by the activity and
   one or two details. Keep every item under two sentences.
8. Never copy any wording from these instructions into your answer.

Reply as four labeled lines. Replace the parentheses with your real answer:
ANSWER: (full sentences answering the question; a numbered list if several things)
SOURCE: (the app or site it came from)
TIME: (when it happened, in local time)
COPY: (a single exact value, only if the question asked for one)"""


def _fts_query(question: str) -> str:
    words = re.findall(r"[a-zA-Z0-9_.-]+", question.lower())
    content = [w for w in words if w not in STOPWORDS and len(w) > 1]
    if not content:
        content = [w for w in words if len(w) > 1] or words
    terms = [f'"{w}"' for w in content]
    # Adjacent word pairs from the original text (real adjacency) as phrases:
    # captures containing the exact phrase score higher under bm25 rank.
    for a, b in zip(words, words[1:]):
        if len(a) > 1 and len(b) > 1 and (a in content or b in content):
            terms.append(f'"{a} {b}"')
    seen: set[str] = set()
    out = []
    for t in terms:  # de-dupe, preserve order
        if t not in seen:
            seen.add(t)
            out.append(t)
    return " OR ".join(out)


def _local_offset() -> str:
    off = datetime.now().astimezone().utcoffset()
    total = int(off.total_seconds() // 60)
    sign = "+" if total >= 0 else "-"
    return f"UTC{sign}{abs(total) // 60:02d}:{abs(total) % 60:02d}"


# Personal facts answered straight from the Vault — no model in the loop.
# Small on-device models are unreliable at needle-extraction; a phone number
# in a trusted file shouldn't depend on one.
FACT_VALUE_PATTERNS = {
    "phone": re.compile(r"(?:\+?1[\s\-.]?)?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}\b"),
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    "address": None,  # line-based
    "birthday": re.compile(r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* \d{1,2},? \d{4})", re.I),
}
FACT_KEYWORDS = {
    "phone": ("phone", "number", "cell", "mobile"),
    "email": ("email", "e-mail", "mail"),
    "address": ("address", "street", "live"),
    "birthday": ("birthday", "birth", "born", "dob"),
}


def vault_fact(conn, question: str) -> dict | None:
    """Deterministic lookup: 'what is my phone number' -> value from a Vault
    file. Returns {answer, source, copy_text} or None (then the model runs)."""
    q = question.lower()
    if "my" not in q:
        return None
    from . import vault
    # Edits to vault files must be visible immediately — reindex is mtime-guarded,
    # so this is a handful of stat() calls when nothing changed.
    try:
        vault.reindex(conn)
    except Exception:
        pass
    rows = conn.execute("SELECT path, content FROM vault_files").fetchall()
    kind = next((k for k, words in FACT_KEYWORDS.items()
                 if any(w in q for w in words)), None)
    if kind is None:
        return _generic_vault_fact(rows, q)
    pattern = FACT_VALUE_PATTERNS[kind]
    q_terms = [t for t in re.findall(r"[a-z0-9]+", q)
               if t not in STOPWORDS and len(t) > 1]
    best = None  # (score, answer, path) — most question terms on the line wins
    for path, content in rows:
        for line in content.splitlines():
            low = line.lower()
            if not any(w in low for w in FACT_KEYWORDS[kind]):
                continue
            value = None
            if pattern:
                m = pattern.search(line)
                if m:
                    value = m.group(0).strip()
            elif ":" in line:  # "Address: 123 Foo St"
                value = line.split(":", 1)[1].strip() or None
            if value:
                score = sum(1 for t in q_terms if t in low)
                if best is None or score > best[0]:
                    best = (score, value, path)
    if best:
        return {"answer": best[1], "source": f"Vault · {best[2]}",
                "copy_text": best[1]}
    # keyword may sit on the line above the value (label on its own line)
    if pattern:
        for path, content in rows:
            lines = content.splitlines()
            for i, line in enumerate(lines[:-1]):
                if any(w in line.lower() for w in FACT_KEYWORDS[kind]):
                    m = pattern.search(lines[i + 1])
                    if m:
                        return {"answer": m.group(0).strip(),
                                "source": f"Vault · {path}",
                                "copy_text": m.group(0).strip()}
    # Typed pattern missed (unusual formatting) — try the generic Label: value path.
    return _generic_vault_fact(rows, q)


def _generic_vault_fact(rows, question: str) -> dict | None:
    """'what is my <anything>' -> best 'Label: value' vault line whose label
    contains the asked terms. Handles PID, license, insurance, wifi name…"""
    m = re.search(r"\bmy\s+(.{2,50}?)(?:\?|$)", question.lower())
    if not m:
        return None
    terms = [t for t in re.findall(r"[a-z0-9]+", m.group(1))
             if t not in STOPWORDS and len(t) > 1]
    if not terms:
        return None
    best = None
    for path, content in rows:
        for line in content.splitlines():
            if ":" not in line:
                continue
            label, _, value = line.partition(":")
            value = value.strip()
            if not value or len(value) > 120:
                continue
            hits = sum(1 for t in terms if t in label.lower())
            if hits and (best is None or hits > best[0]):
                best = (hits, value, path)
    if best and best[0] >= max(1, len(terms) - 1):
        return {"answer": best[1], "source": f"Vault · {best[2]}",
                "copy_text": best[1]}
    return None


def _dedupe_captures(rows: list, limit: int) -> list:
    """Keep the first `limit` captures whose (app + snippet) are distinct — the
    same page recurs across many captures and otherwise fills the window with
    repeats. Preserves rank order (most relevant first)."""
    out: list = []
    seen: list = []
    for r in rows:
        app = r.get("app", "")
        snip = re.sub(r"\s+", " ", (r.get("snippet") or "")).strip().lower()
        head = snip[:45]
        if any(a == app and (head and head == h or (snip and s and (snip in s or s in snip)))
               for a, h, s in seen):
            continue
        seen.append((app, head, snip[:120]))
        out.append(r)
        if len(out) >= limit:
            break
    return out


_ACTIVITY_Q = re.compile(
    r"\b(what (did|have) i (do|done|work(ed)? on)|what was i (doing|working on)|"
    r"summarize|summary of|recap|what happened|how did i spend|what did i get done)\b", re.I)


def build_context(conn, question: str, compact: bool = False) -> tuple[str, dict]:
    """compact=True shrinks everything to fit the on-device model's small
    context window (~4k tokens total including the answer)."""
    since, until, stripped_q = timeparse.parse(question)
    fts = _fts_query(stripped_q)
    n_match = 8 if compact else 12
    # "Generic activity" question — after stripping the time phrase and stopwords
    # there are no real content words left ("what did I do today?"). FTS would
    # then match the literal words what/did/do, dragging in Vault files and old
    # pages that merely contain them ("[what]'s left…" in a portfolio PDF), and
    # the small model reports THOSE as your activity. For these questions the
    # time-window captures ARE the answer — skip keyword retrieval entirely.
    content_words = [w for w in re.findall(r"[a-zA-Z0-9_.-]+", stripped_q.lower())
                     if w not in STOPWORDS and len(w) > 1]
    generic = not content_words
    # Activity questions ("what did I work on", "summarize my day") are about a
    # TIME SPAN, not a keyword — words like "work" would keyword-match portfolio
    # PDFs. Force the window path, and default the window to today when the
    # question implies it but timeparse found no explicit phrase ("my day").
    if _ACTIVITY_Q.search(question):
        generic = True
        if not since and not until:
            since, until, _ = timeparse.parse("today")
    # Hybrid retrieval: FTS keyword rank fused with semantic vector rank (RRF), so
    # "that article about burnout" matches a page that said "exhaustion". Falls
    # back to FTS-only when the embedder is offline. Over-fetch, then drop
    # near-duplicate captures (the same page/session recurs many times) — distinct
    # facts matter more than raw count, especially for the small on-device model.
    from . import embed
    qvec = embed.embed_vec(stripped_q or question)
    rows = []
    if not generic:
        rows = db.search_captures_hybrid(conn, fts, qvec, limit=n_match * 3,
                                         since=since, until=until)
        rows = _dedupe_captures(rows, n_match)
    if not rows:
        # Keyword miss (e.g. "what was due?") — fall back to the most recent
        # captures in the asked time window so Claude still sees something real.
        sql = "SELECT id, ts, app, window_title, url, substr(ocr_text,1,600) FROM captures"
        params: list = []
        if since:
            sql += " WHERE ts >= ?"
            params.append(since)
        if until:
            sql += (" AND" if since else " WHERE") + " ts <= ?"
            params.append(until)
        sql += " ORDER BY id DESC LIMIT ?"
        # Generic day questions live entirely off this window — give them more.
        params.append((10 if generic else 6) if compact else 18)
        cols = ["id", "ts", "app", "window_title", "url", "snippet"]
        rows = [dict(zip(cols, r)) for r in conn.execute(sql, params)]
    # Daily summaries. For a time-bounded question ("today", "this morning"), only
    # include summaries INSIDE that window — otherwise yesterday's digest bleeds in
    # and the small model reports it as today. Untimed questions keep recent ones.
    if since or until:
        ssql = "SELECT date, summary_md, threads_md FROM summaries WHERE 1=1"
        sparams: list = []
        if since:
            ssql += " AND date >= ?"
            sparams.append(since[:10])
        if until:
            ssql += " AND date <= ?"
            sparams.append(until[:10])
        ssql += " ORDER BY date DESC LIMIT ?"
        sparams.append(2 if compact else 3)
        sums = conn.execute(ssql, sparams).fetchall()
    else:
        sums = conn.execute(
            "SELECT date, summary_md, threads_md FROM summaries ORDER BY date DESC LIMIT ?",
            (2 if compact else 3,)).fetchall()

    parts = []
    # Small models weight early tokens heavily — in compact mode the trusted
    # Vault leads the context so it beats noisy screen text.
    from . import memory, vault
    # Generic activity questions have no content terms — Vault "matches" would be
    # stopword hits inside PDFs (portfolio junk the model then narrates as your
    # day). Skip the Vault for them entirely.
    vrows = [] if generic else vault.search(conn, fts, limit=3 if compact else 5)
    if compact and vrows:
        parts.append("## Vault (user-provided files — trusted truth; if Vault and "
                     "screen data conflict, Vault wins)")
        for v in vrows:
            parts.append(f"[vault:{v['path']}]\n{v['snippet']}")
    # Lead with what's on screen right now — most questions are about it. But a
    # question about a PAST window ("yesterday") must not open with today's
    # screen: the small model anchors on it and reports the wrong day.
    window_is_past = bool(until) and until < db.utcnow()
    recent = [] if window_is_past else db.recent_captures(
        conn, limit=2, max_chars=800 if compact else 1100)
    # Window-bounded question: the recent block must not smuggle in captures
    # from OUTSIDE the window (e.g. an old wisp when today is nearly empty).
    if since:
        recent = [r for r in recent if r["ts"] >= since]
    if recent:
        parts.append("## Current / most recent screen (full text)")
        for r in recent:
            hdr = f"[#{r['id']} {r['app']} {r['ts']} UTC]"
            loc = f" url={r['url']}" if r["url"] else (f" window={r['window_title']}" if r["window_title"] else "")
            parts.append(f"{hdr}{loc}\n{r['ocr_text']}")
    recent_ids = {r["id"] for r in recent}
    rows = [r for r in rows if r["id"] not in recent_ids]
    # The 48-token FTS snippet often clips the actual answer a sentence away from
    # the matched keyword. Give the top matches fuller text around the hit.
    top_ids = [r["id"] for r in rows[: (3 if compact else 5)]]
    if top_ids:
        span = 600 if compact else 600
        full = {i: t for i, t in conn.execute(
            f"SELECT id, substr(ocr_text,1,{span}) FROM captures "
            f"WHERE id IN ({','.join('?' * len(top_ids))})", top_ids)}
        for r in rows:
            if r["id"] in full and full[r["id"]]:
                r["snippet"] = full[r["id"]]
    if rows:
        parts.append("## Screen captures (matched)")
        for r in rows:
            hdr = f"[#{r['id']} {r['app']} {r['ts']} UTC]"
            loc = f" url={r['url']}" if r["url"] else (f" window={r['window_title']}" if r["window_title"] else "")
            parts.append(f"{hdr}{loc}\n{r['snippet']}")
    if sums:
        parts.append("## Daily summaries")
        for d, s, t in sums:
            parts.append(f"[summary {d}]\n{s or ''}\nThreads: {t or ''}")
    # Consolidated episodes (Dream Mode) — clean summaries of older sessions that
    # the raw wisps may have already aged out of. Cheap to include, high signal.
    try:
        from . import dream
        eps = dream.search_episodes(conn, fts, qvec, limit=2 if compact else 3)
        # A time-bounded question must not surface other days' episodes — old
        # "what I did" summaries are exactly what a small model mistakes for today.
        if since or until:
            eps = [e for e in eps
                   if (not since or e["span"][:10] >= since[:10])
                   and (not until or e["span"][:10] <= until[:10])]
        if eps:
            parts.append("## Past episodes (consolidated memory)")
            for e in eps:
                parts.append(f"[episode {e['span'][:10]}] {e['title']}\n{e['summary'][:400]}")
    except Exception:  # noqa: BLE001
        pass
    if vrows and not compact:
        parts.append("## Vault (user-provided files — trusted truth; if Vault and "
                     "screen data conflict, Vault wins)")
        for v in vrows:
            parts.append(f"[vault:{v['path']}]\n{v['snippet']}")
    confirmed = memory.confirmed_text()
    if confirmed:
        parts.append("## Confirmed memory about the user\n" + confirmed)

    # Names are the single most-forgotten retrospective item (diary studies), so
    # "who …" questions get the names bank from recent episodes as extra context.
    if re.match(r"\s*who(?:'s|se| was| is| did| do)?\b", question, re.I):
        try:
            import json as _json
            from collections import Counter
            names: Counter = Counter()
            for (ej,) in conn.execute(
                    "SELECT entities_json FROM episodes ORDER BY id DESC LIMIT 20"):
                for e in _json.loads(ej or "[]"):
                    if " " in e or len(e) > 3:      # skip acronym noise
                        names[e] += 1
            if names:
                parts.append("## Names seen recently (people, orgs, products)\n"
                             + ", ".join(n for n, _ in names.most_common(15)))
        except Exception:  # noqa: BLE001
            pass

    # Reinforcement: the wisps that actually fed an answer count as recalled —
    # they strengthen (rank higher next time, survive retention longer).
    recalled_ids = [r["id"] for r in rows[:5]]
    if recalled_ids:
        try:
            db.bump_recall(conn, recalled_ids)
        except Exception:  # noqa: BLE001
            pass
    meta = {"since": since, "until": until, "fts": fts, "n_captures": len(rows)}
    text = "\n\n".join(parts)
    # Hard caps: tight for the on-device window; also bound the cloud prompt so a
    # dense day doesn't balloon it to 30k+ chars and make Claude slow to read.
    text = text[:9000] if compact else text[:15000]
    return text, meta


_DELTA_INTENT = re.compile(
    r"\b(what('?s| is| has|)\s+(new|changed|different|updated)|any(thing)?\s+(new|change)"
    r"|what'?s new|since (i )?last|diff(ed|erence)?|what did .* change)\b", re.I)


def delta_answer(conn, question: str) -> dict | None:
    """Deterministic 'what changed on this page' answer — diffs the current page
    against its previous version (or the version before a parsed 'since Tuesday').
    Returns a fact-shaped dict (answer/detail/source/copy_text/model) or None."""
    if not _DELTA_INTENT.search(question):
        return None
    from . import delta
    since, _until, _stripped = timeparse.parse(question)
    key = db.latest_page_key(conn)
    if not key:
        return None
    old, new = db.versions_for_key(conn, key, before=since)
    if not new or not old:
        return None
    d = delta.diff_texts(old["ocr_text"], new["ocr_text"])
    if not (d["added"] or d["removed"] or d["changed"]):
        return {"answer": "Nothing has changed on this page since you last saw it.",
                "source": f"Delta · {_pretty_key(key)}", "copy_text": "", "model": "Delta"}

    def _fmt(lines, mark):
        return "\n".join(f"{mark} {ln}" for ln in lines[:12])
    parts = []
    if d["added"]:
        parts.append("Added\n" + _fmt(d["added"], "+"))
    if d["changed"]:
        parts.append("Changed\n" + "\n".join(
            f"• {c['old']}  →  {c['new']}" for c in d["changed"][:12]))
    if d["removed"]:
        parts.append("Removed\n" + _fmt(d["removed"], "−"))
    detail = "\n\n".join(parts)
    span = f"{_short_ts(old['ts'])} → {_short_ts(new['ts'])}"
    return {"answer": delta.summarize(d),
            "detail": detail,
            "source": f"Delta · {_pretty_key(key)}",
            "time": span,
            "copy_text": detail,
            "model": "Delta"}


def _pretty_key(key: str) -> str:
    if key.startswith("http"):
        return key.split("://", 1)[-1][:60]
    return key.split("::", 1)[0][:40]


def _short_ts(ts: str) -> str:
    return (ts or "")[5:16].replace("-", "/")  # 'MM/DD HH:MM' from 'YYYY-MM-DD HH:MM:SS'


def build_prompt(question: str, compact: bool = False) -> tuple[str, dict]:
    """Full prompt (rules + context + question). Used by the Swift app to run
    the Apple on-device model — retrieval stays here, generation happens there."""
    conn = db.connect()
    try:
        # Deterministic hits skip the model entirely: 'what changed here' -> a
        # page diff; 'how has my weight moved' -> a tracked series; a personal
        # fact -> the exact Vault value.
        from . import forgetting, numbers, precog
        precog.log_query(conn, question)   # feeds Precognition's guesses
        fact = (forgetting.pinned_answer(conn, question)
                or delta_answer(conn, question) or numbers.lookup(conn, question)
                or vault_fact(conn, question))
        context, meta = build_context(conn, question, compact=compact)
        if fact:
            meta["fact"] = fact
        now_local = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %A")
        rules = COMPACT_SYSTEM_RULES if compact else SYSTEM_RULES
        # Fence the retrieved text and say plainly that it is data. Rewisp reads
        # pages an attacker may control, so the context is genuinely untrusted
        # input to a model that can also see the Vault — indirect prompt
        # injection, OWASP LLM01. See rewisp/sanitize.py for the reasoning.
        from . import sanitize
        fence = sanitize.new_fence()
        safe_context = sanitize.scrub(context, fence)
        prompt = (f"{rules}\n\n{sanitize.TRUST_NOTICE}\n\n"
                  f"User's local time now: {now_local} ({_local_offset()})\n\n"
                  f"# CONTEXT [begin {fence}]\n{safe_context}\n[end {fence}]\n\n"
                  f"# QUESTION\n{question}")
        return prompt, meta
    finally:
        conn.close()


def _call_claude(prompt: str) -> str:
    """One call through Claude Code (Pro subscription). Refuses to run with an API key set."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is set — this would bill the API instead of your "
            "Claude subscription. Unset it and retry.")
    claude = cli_path("claude")
    if not claude:
        raise RuntimeError("Claude Code CLI not found. Install it and run `claude` once to sign in.")
    # Speed: skip the MCP servers, project settings, and CLAUDE.md the CLI would
    # otherwise spawn/load on every call (that overhead is most of the latency).
    # Run from a neutral cwd for the same reason. Keychain auth is untouched.
    out = subprocess.run(
        [claude, "-p", "--output-format", "text",
         "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
         "--setting-sources", "user"],
        input=prompt, capture_output=True, text=True, timeout=120,
        cwd="/tmp",
    )
    if out.returncode != 0:
        err = (out.stderr or out.stdout).strip()
        if "log in" in err.lower() or "auth" in err.lower():
            raise RuntimeError("Claude Code is signed out. Run `claude` in a terminal and sign in.")
        raise RuntimeError(f"claude call failed: {err[:400]}")
    return out.stdout.strip()


def _call_codex(prompt: str) -> str:
    """ChatGPT Plus path: OpenAI's Codex CLI, billed to the ChatGPT subscription.
    Same rule as Claude — refuse to silently bill an API key."""
    if os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is set — this would bill the OpenAI API instead of your "
            "ChatGPT subscription. Unset it and retry.")
    codex = cli_path("codex")
    if not codex:
        raise RuntimeError("Codex CLI not found. `npm i -g @openai/codex`, then `codex` once to sign in.")
    out = subprocess.run(
        [codex, "exec", "--skip-git-repo-check", "-"],
        input=prompt, capture_output=True, text=True, timeout=180,
    )
    if out.returncode != 0:
        raise RuntimeError(f"codex call failed: {(out.stderr or out.stdout).strip()[:400]}")
    # codex exec prints session preamble lines before the answer; the answer is
    # the text after the final "codex" marker line, when present.
    text = out.stdout.strip()
    if "\ncodex\n" in text:
        text = text.rsplit("\ncodex\n", 1)[1]
    return text.strip()


def _ssl_context():
    """python.org Python ships without system CA certs, so plain HTTPS to Google
    fails cert verification. Prefer certifi's bundle; fall back to system default."""
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def _call_gemini(prompt: str) -> str:
    """Free cloud path: Google Gemini free tier. Strong answers, no local install,
    no paid API — uses the user's own free key from aistudio.google.com. Requires
    a network call, so it only runs when a key is set in settings."""
    import json as _json
    import urllib.error
    import urllib.request
    s = config.load_settings()
    key = (s.get("gemini_api_key") or "").strip()
    if not key:
        raise RuntimeError(
            "No Gemini key. Get a free one at aistudio.google.com/apikey and paste "
            "it in Settings to enable the free cloud engine.")
    import re as _re
    import time as _time
    model = s.get("gemini_model", "gemini-2.5-flash")
    payload = _json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 700},
    }).encode()

    def _post(api: str) -> tuple[int, str]:
        url = (f"https://generativelanguage.googleapis.com/{api}/models/"
               f"{model}:generateContent?key={key}")
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json",
                     "User-Agent": _user_agent()})
        try:
            with urllib.request.urlopen(req, timeout=60, context=_ssl_context()) as resp:
                return 200, resp.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(errors="replace")

    # Newer models (2.5+) live on v1; older ones answer on v1beta. Try v1 first,
    # fall back to v1beta on a 404 so any model the user picks works.
    try:
        code, body = _post("v1")
        if code == 404:
            code, body = _post("v1beta")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Gemini not reachable ({e.reason}).") from e

    # One retry on 429, honoring the server's suggested "retry in Ns" (capped).
    if code == 429 and "limit: 0" not in body:
        m = _re.search(r"retry in ([\d.]+)s", body)
        _time.sleep(min(float(m.group(1)) + 1, 20) if m else 5)
        code, body = _post("v1")
        if code == 404:
            code, body = _post("v1beta")

    if code == 429 and "limit: 0" in body:
        raise RuntimeError(
            "This Google account has no Gemini free tier (limit 0). Workspace / "
            "school accounts (e.g. .edu) block it — create the key from a personal "
            "Google account at aistudio.google.com/apikey.")
    if code == 429:
        raise RuntimeError("Gemini free-tier daily/rate limit reached — try later.")
    if code != 200:
        raise RuntimeError(f"Gemini call failed ({code}): {body[:200]}")
    try:
        return _json.loads(body)["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError, ValueError) as e:
        raise RuntimeError(f"Gemini returned no answer: {body[:200]}") from e


def gemini_selftest() -> tuple[bool, str | None]:
    """Actually call Gemini once so the UI can confirm the key WORKS, not just
    that it's non-empty — catches disabled free tier, bad keys, and network gaps."""
    try:
        _call_gemini("Reply with the single word: ok")
        return True, None
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def _call_local(prompt: str) -> str:
    """Free, unlimited, offline, private: a local MLX model on Apple Silicon.
    Nothing leaves the Mac. Starts the model server on demand."""
    import json as _json
    import urllib.request
    from . import localmodel
    model_id = localmodel.active_model()
    if not model_id:
        raise RuntimeError("No local model downloaded yet — set one up in Settings "
                           "(or Onboarding) to use the free offline engine.")
    ok, err = localmodel.ensure_server(model_id)
    if not ok:
        raise RuntimeError(err or "local model server unavailable")
    # Disable "thinking": these 2026 models reason into a separate field by
    # default and would burn the whole token budget before writing the answer.
    # enable_thinking=false makes them answer directly — faster and cleaner.
    payload = {"model": localmodel._repo_for(model_id),
               "messages": [{"role": "user", "content": prompt}],
               "temperature": 0.2, "max_tokens": 512,
               "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(
        f"http://127.0.0.1:{localmodel.PORT}/v1/chat/completions",
        data=_json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": _user_agent()})
    with urllib.request.urlopen(req, timeout=240) as resp:
        data = _json.loads(resp.read())
    msg = data["choices"][0].get("message", {})
    text = (msg.get("content") or "").strip()
    if not text:  # model exhausted tokens on reasoning — use that as a fallback
        text = (msg.get("reasoning") or "").strip()
    # Strip any <think>…</think> block some reasoning models inline into content.
    text = re.sub(r"(?is)<think>.*?</think>", "", text).strip()
    return text


def _user_agent() -> str:
    """Identify ourselves on outbound API calls.

    urllib defaults to "Python-urllib/3.x", which a lot of providers sitting
    behind Cloudflare reject outright — it comes back as HTTP 403 with
    "error code: 1010" ("banned based on your browser's signature"). The key and
    model are fine; the request never reaches the provider at all. Reported by a
    user whose custom API failed against several different models.
    """
    from . import __version__
    return f"Rewisp/{__version__} (macOS; +https://github.com/yashmitb/Rewisp)"


def _call_custom(prompt: str) -> str:
    """Any paid OpenAI-compatible API the user already pays for (OpenAI, DeepSeek,
    Groq, OpenRouter, Mistral…). They opt in and provide their own key/URL."""
    import json as _json
    import urllib.error
    import urllib.request
    c = config.load_settings().get("custom_api") or {}
    base = (c.get("base_url") or "").strip().rstrip("/")
    key = (c.get("api_key") or "").strip()
    model = (c.get("model") or "").strip()
    if not (base and key and model):
        raise RuntimeError("Custom API not set up — add base URL, key, and model in Settings.")
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}],
               "temperature": 0.2, "max_tokens": 400}
    req = urllib.request.Request(
        base + "/chat/completions", data=_json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}",
                 "Accept": "application/json",
                 "User-Agent": _user_agent()})
    try:
        with urllib.request.urlopen(req, timeout=120, context=_ssl_context()) as resp:
            data = _json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        if e.code in (403, 503) and "1010" in body:
            raise RuntimeError(
                "Custom API blocked by Cloudflare (error 1010). The provider is "
                "rejecting the request before it reaches them. Check the base URL "
                "is the API endpoint (usually ending in /v1) and not a dashboard "
                "or proxy page.") from e
        if e.code == 401:
            raise RuntimeError("Custom API rejected the key (401). Check the API "
                               "key and that it has access to this model.") from e
        if e.code == 404:
            raise RuntimeError(f"Custom API returned 404. Check the base URL — it "
                               f"should end in /v1, and Rewisp appends "
                               f"/chat/completions.") from e
        raise RuntimeError(f"Custom API failed ({e.code}): {body[:150]}") from e
    return data["choices"][0]["message"]["content"].strip()


def _call_ollama(prompt: str) -> str:
    """Free path: local Ollama server. Fully free and unlimited, but a small
    local model — noticeably weaker than Claude/ChatGPT."""
    import json as _json
    import urllib.error
    import urllib.request
    model = config.load_settings().get("ollama_model", "llama3.1:8b")
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=_json.dumps({"model": model, "prompt": prompt,
                          "stream": False, "options": {"temperature": 0.2}}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": _user_agent()})
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return _json.loads(resp.read())["response"].strip()
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Ollama not reachable ({e.reason}). Install from ollama.com, then "
            f"`ollama pull {model}`.") from e


ENGINES = {"claude": _call_claude, "codex": _call_codex, "custom": _call_custom,
           "local": _call_local, "gemini": _call_gemini, "ollama": _call_ollama}
# Auto order, best-first: Claude Pro -> ChatGPT (Codex) -> user's paid custom API ->
# local MLX (free, private, offline) -> Gemini free cloud -> Ollama. Local sits ahead
# of cloud Gemini because it's private and unlimited; each engine self-skips when it
# isn't set up, so the chain falls through to whatever the user actually has.
AUTO_ORDER = ["claude", "codex", "custom", "local", "gemini", "ollama"]


def _engine_label(engine: str) -> str:
    if engine == "local":
        from . import localmodel
        mid = localmodel.active_model()
        return f"Local · {localmodel.MODELS[mid]['label']}" if mid else "Local"
    if engine == "custom":
        c = config.load_settings().get("custom_api") or {}
        return c.get("label") or "Custom API"
    return {"claude": "Claude", "codex": "ChatGPT", "gemini": "Gemini (free)",
            "ollama": "Ollama (local)"}.get(engine, engine)


def call_claude(prompt: str) -> str:
    """Kept name for existing callers; routes through the configured engine."""
    return call_llm(prompt)[0]


def call_llm(prompt: str) -> tuple[str, str]:
    """(answer, engine_used). engine setting: auto | claude | codex | custom | local |
    gemini | ollama. auto walks AUTO_ORDER, skipping any in disabled_engines, and
    falls through to whatever the user actually has configured."""
    s = config.load_settings()
    engine = s.get("engine", "auto")
    disabled = set(s.get("disabled_engines") or [])
    if engine == "auto":
        order = [e for e in AUTO_ORDER if e not in disabled]
        if not order:
            raise RuntimeError("No engines enabled. Turn one back on in "
                               "Settings → Answers → Advanced.")
    else:
        # Chosen engine is a preference, not a hard lock: try it first, then fall
        # back to the rest of the chain. So "Gemini" is fast day-to-day and Claude
        # quietly covers it when Gemini hits its free daily limit.
        order = [engine] + [e for e in AUTO_ORDER if e != engine and e not in disabled]
    errors = []
    for name in order:
        try:
            return ENGINES[name](prompt), name
        except Exception as e:  # noqa: BLE001 — each engine failure falls through
            errors.append(f"{name}: {e}")
    raise RuntimeError("All engines failed — " + " | ".join(errors))


def parse_answer(raw: str) -> dict:
    """Split Claude's ANSWER/DETAIL/SOURCE/TIME/COPY format into fields.
    Unparseable output falls back to the whole text as the answer."""
    fields = {"answer": None, "detail": None, "source": None,
              "time": None, "copy_text": None}
    keymap = {"ANSWER": "answer", "DETAIL": "detail", "SOURCE": "source",
              "TIME": "time", "COPY": "copy_text"}
    current = None
    for line in raw.splitlines():
        m = re.match(r"^(ANSWER|DETAIL|SOURCE|TIME|COPY):\s*(.*)$", line)
        if m:
            current = keymap[m.group(1)]
            fields[current] = m.group(2).strip()
        elif current and line.strip():
            fields[current] = (fields[current] + "\n" + line.rstrip()).strip()
    if not fields["answer"]:
        fields["answer"] = raw.strip()
    return fields


def near_misses(conn, question: str, limit: int = 3) -> str | None:
    """Closest moments for a failed search. Re-finding research: ~40% of queries
    are re-finding, and people misremember their own original wording ~30% of the
    time — so a flat "not found" is a dead end exactly when the user needs a
    nudge. Show the nearest things Rewisp DID see instead."""
    from . import embed
    from .dejavu import clean_snippet
    qvec = embed.embed_vec(question)
    try:
        rows = db.search_captures_hybrid(conn, _fts_query(question) or '""', qvec,
                                         limit=limit * 3)
    except Exception:  # noqa: BLE001 — rescue must never break the answer path
        return None
    rows = _dedupe_captures(rows, limit * 2)
    lines = []
    for r in rows:
        snip = clean_snippet(r.get("snippet") or "", 90)
        if len(snip) < 12:
            continue
        when = (r.get("ts") or "")[5:16]
        lines.append(f"• {r.get('app','')} · {when}: {snip}")
        if len(lines) >= limit:
            break
    if not lines:
        return None
    return "Closest moments in your memory:\n" + "\n".join(lines)


def ask(question: str, save: bool = True) -> tuple[str, dict]:
    conn = db.connect()
    from . import forgetting, numbers
    fact = (forgetting.pinned_answer(conn, question) or delta_answer(conn, question)
            or numbers.lookup(conn, question) or vault_fact(conn, question))
    if fact:
        meta = {"answer": fact["answer"], "source": fact.get("source"),
                "detail": fact.get("detail"), "time": fact.get("time"),
                "copy_text": fact.get("copy_text"), "model": fact.get("model", "Vault"),
                "n_captures": 0}
        if save:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("INSERT INTO chats (ts, role, content) VALUES (?, 'user', ?)", (ts, question))
            conn.execute("INSERT INTO chats (ts, role, content) VALUES (?, 'assistant', ?)", (ts, fact["answer"]))
            conn.commit()
        return fact["answer"], meta
    context, meta = build_context(conn, question)
    if not context.strip():
        return "Not found in your memory. (No matching captures.)", meta
    now_local = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %A")
    # Same fencing as build_prompt. This is the path that reaches CLOUD engines,
    # so leaving it raw would have been the more exposed of the two.
    from . import sanitize
    fence = sanitize.new_fence()
    prompt = (f"{SYSTEM_RULES}\n\n{sanitize.TRUST_NOTICE}\n\n"
              f"User's local time now: {now_local} ({_local_offset()})\n\n"
              f"# CONTEXT [begin {fence}]\n{sanitize.scrub(context, fence)}\n"
              f"[end {fence}]\n\n# QUESTION\n{question}")
    raw, engine = call_llm(prompt)
    fields = parse_answer(raw)
    # Failed re-find -> show the nearest moments instead of a dead end (the user
    # likely misremembered the wording, not imagined the memory).
    if "not found in your memory" in (fields.get("answer") or "").lower():
        misses = near_misses(conn, question)
        if misses:
            fields["detail"] = (fields.get("detail") or "").strip()
            fields["detail"] = (fields["detail"] + "\n\n" + misses).strip()
    meta.update(fields)
    meta["model"] = _engine_label(engine)
    answer = fields["answer"]
    if save:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("INSERT INTO chats (ts, role, content) VALUES (?, 'user', ?)", (ts, question))
        conn.execute("INSERT INTO chats (ts, role, content) VALUES (?, 'assistant', ?)", (ts, answer))
        conn.commit()
        try:
            from . import forgetting
            forgetting.maybe_pin(conn, question, answer)   # 3rd lookup -> pinned
        except Exception:  # noqa: BLE001
            pass
    return answer, meta
