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
    # Small models weight early tokens heavily — in compact mode the trusted
    # Vault leads the context so it beats noisy screen text.
    from . import memory, vault
    vrows = vault.search(conn, fts, limit=3 if compact else 5)
    if compact and vrows:
        parts.append("## Vault (user-provided files — trusted truth; if Vault and "
                     "screen data conflict, Vault wins)")
        for v in vrows:
            parts.append(f"[vault:{v['path']}]\n{v['snippet']}")
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
    if vrows and not compact:
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
        # Deterministic personal-fact hit: skip the model entirely.
        fact = vault_fact(conn, question)
        context, meta = build_context(conn, question, compact=compact)
        if fact:
            meta["fact"] = fact
        now_local = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %A")
        prompt = (f"{SYSTEM_RULES}\n\nUser's local time now: {now_local} ({_local_offset()})\n\n"
                  f"# Context\n{context}\n\n# Question\n{question}")
        return prompt, meta
    finally:
        conn.close()


def _call_claude(prompt: str) -> str:
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


def _call_codex(prompt: str) -> str:
    """ChatGPT Plus path: OpenAI's Codex CLI, billed to the ChatGPT subscription.
    Same rule as Claude — refuse to silently bill an API key."""
    if os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is set — this would bill the OpenAI API instead of your "
            "ChatGPT subscription. Unset it and retry.")
    if not shutil.which("codex"):
        raise RuntimeError("Codex CLI not found. `npm i -g @openai/codex`, then `codex` once to sign in.")
    out = subprocess.run(
        ["codex", "exec", "--skip-git-repo-check", "-"],
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
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return _json.loads(resp.read())["response"].strip()
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Ollama not reachable ({e.reason}). Install from ollama.com, then "
            f"`ollama pull {model}`.") from e


ENGINES = {"claude": _call_claude, "codex": _call_codex, "ollama": _call_ollama}
AUTO_ORDER = ["claude", "codex", "ollama"]  # best quality first


def call_claude(prompt: str) -> str:
    """Kept name for existing callers; routes through the configured engine."""
    return call_llm(prompt)[0]


def call_llm(prompt: str) -> tuple[str, str]:
    """(answer, engine_used). engine setting: auto | claude | codex | ollama.
    auto = try Claude (best), then ChatGPT Plus via Codex, then free local Ollama."""
    engine = config.load_settings().get("engine", "auto")
    order = AUTO_ORDER if engine == "auto" else [engine]
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


def ask(question: str, save: bool = True) -> tuple[str, dict]:
    conn = db.connect()
    fact = vault_fact(conn, question)
    if fact:
        meta = {"answer": fact["answer"], "source": fact["source"],
                "copy_text": fact["copy_text"], "model": "Vault", "n_captures": 0}
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
    prompt = (f"{SYSTEM_RULES}\n\nUser's local time now: {now_local} ({_local_offset()})\n\n"
              f"# Context\n{context}\n\n# Question\n{question}")
    raw, engine = call_llm(prompt)
    fields = parse_answer(raw)
    meta.update(fields)
    meta["model"] = {"claude": "Claude", "codex": "ChatGPT",
                     "ollama": "Ollama (local)"}.get(engine, engine)
    answer = fields["answer"]
    if save:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("INSERT INTO chats (ts, role, content) VALUES (?, 'user', ?)", (ts, question))
        conn.execute("INSERT INTO chats (ts, role, content) VALUES (?, 'assistant', ?)", (ts, answer))
        conn.commit()
    return answer, meta
