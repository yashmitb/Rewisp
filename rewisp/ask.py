"""Ask pipeline: local time parse -> FTS retrieval -> one Claude call (Claude Code
subscription, never an API key) -> answer with sources -> saved to chats."""

import os
import re
import shutil
import subprocess
from datetime import datetime, timezone

from . import config, db, timeparse

STOPWORDS = {
    "a", "an", "the", "i", "me", "my", "was", "is", "are", "were", "what", "which",
    "that", "this", "it", "of", "to", "in", "on", "at", "for", "from", "and", "or",
    "did", "do", "does", "have", "had", "has", "with", "about", "you", "can", "get",
    "find", "show", "tell", "there", "where", "when", "who", "how", "why", "right",
    "before", "after", "during", "some", "any", "again", "saw", "see", "looked",
    "looking", "open", "opened", "remember", "up", "past", "by",
}

SYSTEM_RULES = """You are Rewisp, answering questions about the user's own screen history.
Answer ONLY from the context below. If the answer is not in the context, put
"Not found in your memory." in ANSWER — never guess or use outside knowledge.
Timestamps in context are UTC; the user's local timezone offset is given. Convert times to local.

Respond in EXACTLY this format (omit a line entirely if not applicable):
ANSWER: <the direct answer, 1-2 sentences, no citations here>
DETAIL: <supporting explanation or extra findings, brief>
SOURCE: <where it was seen: app / site / file, human-readable>
TIME: <when it was seen, local time, e.g. "Today 4:13 PM" or "Mon Jul 6, 9:02 PM">
COPY: <if the question asked for a specific fact/value (name, ID, address, email,
link, number): the exact bare value alone, nothing else>"""


def _fts_query(question: str) -> str:
    words = re.findall(r"[a-zA-Z0-9_.-]+", question.lower())
    keep = [w for w in words if w not in STOPWORDS and len(w) > 1]
    if not keep:
        keep = words
    # OR of quoted terms: broad recall, rank sorts by relevance
    return " OR ".join(f'"{w}"' for w in keep)


def _local_offset() -> str:
    off = datetime.now().astimezone().utcoffset()
    total = int(off.total_seconds() // 60)
    sign = "+" if total >= 0 else "-"
    return f"UTC{sign}{abs(total) // 60:02d}:{abs(total) % 60:02d}"


def build_context(conn, question: str, compact: bool = False) -> tuple[str, dict]:
    """compact=True shrinks everything to fit the on-device model's small
    context window (~4k tokens total including the answer)."""
    since, until, stripped_q = timeparse.parse(question)
    fts = _fts_query(stripped_q)
    n_match = 8 if compact else 25
    rows = db.search_captures(conn, fts, limit=n_match, since=since, until=until)
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
        params.append(6 if compact else 15)
        cols = ["id", "ts", "app", "window_title", "url", "snippet"]
        rows = [dict(zip(cols, r)) for r in conn.execute(sql, params)]
    # summaries too (once Digest exists)
    sums = conn.execute(
        "SELECT date, summary_md, threads_md FROM summaries ORDER BY date DESC LIMIT ?",
        (2 if compact else 7,)).fetchall()

    parts = []
    # Always lead with what's on screen right now — most questions are about it.
    recent = db.recent_captures(conn, limit=2 if compact else 3,
                                max_chars=800 if compact else 1500)
    if recent:
        parts.append("## Current / most recent screen (full text)")
        for r in recent:
            hdr = f"[#{r['id']} {r['app']} {r['ts']} UTC]"
            loc = f" url={r['url']}" if r["url"] else (f" window={r['window_title']}" if r["window_title"] else "")
            parts.append(f"{hdr}{loc}\n{r['ocr_text']}")
    recent_ids = {r["id"] for r in recent}
    rows = [r for r in rows if r["id"] not in recent_ids]
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
    from . import memory, vault
    vrows = vault.search(conn, fts, limit=2 if compact else 5)
    if vrows:
        parts.append("## Vault (user-provided files — trusted truth; if Vault and "
                     "screen data conflict, Vault wins)")
        for v in vrows:
            parts.append(f"[vault:{v['path']}]\n{v['snippet']}")
    confirmed = memory.confirmed_text()
    if confirmed:
        parts.append("## Confirmed memory about the user\n" + confirmed)

    meta = {"since": since, "until": until, "fts": fts, "n_captures": len(rows)}
    text = "\n\n".join(parts)
    if compact:
        text = text[:9000]  # hard cap for the ~4k-token on-device window
    return text, meta


def build_prompt(question: str, compact: bool = False) -> tuple[str, dict]:
    """Full prompt (rules + context + question). Used by the Swift app to run
    the Apple on-device model — retrieval stays here, generation happens there."""
    conn = db.connect()
    try:
        context, meta = build_context(conn, question, compact=compact)
        now_local = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %A")
        prompt = (f"{SYSTEM_RULES}\n\nUser's local time now: {now_local} ({_local_offset()})\n\n"
                  f"# Context\n{context}\n\n# Question\n{question}")
        return prompt, meta
    finally:
        conn.close()


def call_claude(prompt: str) -> str:
    """One call through Claude Code (Pro subscription). Refuses to run with an API key set."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is set — this would bill the API instead of your "
            "Claude subscription. Unset it and retry.")
    if not shutil.which("claude"):
        raise RuntimeError("Claude Code CLI not found. Install it and run `claude` once to sign in.")
    out = subprocess.run(
        ["claude", "-p", "--output-format", "text"],
        input=prompt, capture_output=True, text=True, timeout=120,
    )
    if out.returncode != 0:
        err = (out.stderr or out.stdout).strip()
        if "log in" in err.lower() or "auth" in err.lower():
            raise RuntimeError("Claude Code is signed out. Run `claude` in a terminal and sign in.")
        raise RuntimeError(f"claude call failed: {err[:400]}")
    return out.stdout.strip()


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


def ask(question: str, save: bool = True) -> tuple[str, dict]:
    conn = db.connect()
    context, meta = build_context(conn, question)
    if not context.strip():
        return "Not found in your memory. (No matching captures.)", meta
    now_local = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %A")
    prompt = (f"{SYSTEM_RULES}\n\nUser's local time now: {now_local} ({_local_offset()})\n\n"
              f"# Context\n{context}\n\n# Question\n{question}")
    raw = call_claude(prompt)
    fields = parse_answer(raw)
    meta.update(fields)
    meta["model"] = "Claude"
    answer = fields["answer"]
    if save:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("INSERT INTO chats (ts, role, content) VALUES (?, 'user', ?)", (ts, question))
        conn.execute("INSERT INTO chats (ts, role, content) VALUES (?, 'assistant', ?)", (ts, answer))
        conn.commit()
    return answer, meta
