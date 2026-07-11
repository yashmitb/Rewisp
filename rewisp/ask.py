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

Rules, in order of importance:
1. Answer ONLY from the context below. Never use outside knowledge, never guess.
2. If the answer is not clearly present, put EXACTLY "Not found in your memory."
   in ANSWER and stop. A wrong answer is far worse than admitting you don't know.
3. When several captures could answer, prefer the MOST RECENT one (highest #id / latest TIME).
4. Quote exact values (names, numbers, links, IDs) verbatim from the context — do not paraphrase them.
5. Timestamps in context are UTC; the user's local offset is given. Convert every TIME you output to local.
6. Vault entries are user-provided truth — if Vault and screen text conflict, Vault wins.

Respond in EXACTLY this format (omit a line entirely if it does not apply):
ANSWER: <the direct answer, 1-2 sentences, no citations here>
DETAIL: <supporting explanation or extra findings, brief>
SOURCE: <where it was seen: app / site / file, human-readable>
TIME: <when it was seen, local time, e.g. "Today 4:13 PM" or "Mon Jul 6, 9:02 PM">
COPY: <if the question asked for a specific fact/value (name, ID, address, email,
link, number): the exact bare value alone, nothing else>"""


# Small on-device models (~3B) follow short, blunt, example-led instructions far
# better than long rule lists. This is tuned for Apple Foundation Models.
COMPACT_SYSTEM_RULES = """You search the user's own screen history and answer from it.

Use ONLY the CONTEXT below. Do not use outside knowledge. Do not invent anything.
If the answer is not clearly in the context, reply exactly: ANSWER: Not found in your memory.
If several captures fit, use the most recent one.
Copy exact values (numbers, emails, links, names) letter-for-letter.

Reply in this format and nothing else:
ANSWER: <one short sentence>
SOURCE: <app or site it came from>
TIME: <when, in the user's local time>
COPY: <only if a specific value was asked for: just the value>

Example:
CONTEXT: [#42 Mail 2026-07-08 22:10 UTC] From: Dana Lee <dana@acme.com> Subject: Invoice #7781 due Friday
QUESTION: who emailed me about an invoice?
ANSWER: Dana Lee emailed you about Invoice #7781, due Friday.
SOURCE: Mail
TIME: Jul 8, 3:10 PM
COPY: dana@acme.com"""


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
    # The 48-token FTS snippet often clips the actual answer a sentence away from
    # the matched keyword. Give the top matches fuller text around the hit.
    top_ids = [r["id"] for r in rows[: (3 if compact else 6)]]
    if top_ids:
        span = 600 if compact else 900
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
        rules = COMPACT_SYSTEM_RULES if compact else SYSTEM_RULES
        prompt = (f"{rules}\n\nUser's local time now: {now_local} ({_local_offset()})\n\n"
                  f"# CONTEXT\n{context}\n\n# QUESTION\n{question}")
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
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 400},
    }).encode()

    def _post(api: str) -> tuple[int, str]:
        url = (f"https://generativelanguage.googleapis.com/{api}/models/"
               f"{model}:generateContent?key={key}")
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"})
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
        data=_json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=240) as resp:
        data = _json.loads(resp.read())
    msg = data["choices"][0].get("message", {})
    text = (msg.get("content") or "").strip()
    if not text:  # model exhausted tokens on reasoning — use that as a fallback
        text = (msg.get("reasoning") or "").strip()
    # Strip any <think>…</think> block some reasoning models inline into content.
    text = re.sub(r"(?is)<think>.*?</think>", "", text).strip()
    return text


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
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=120, context=_ssl_context()) as resp:
            data = _json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Custom API failed ({e.code}): "
                           f"{e.read().decode(errors='replace')[:150]}") from e
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
        headers={"Content-Type": "application/json"})
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
    if engine == "auto":
        disabled = set(s.get("disabled_engines") or [])
        order = [e for e in AUTO_ORDER if e not in disabled]
    else:
        order = [engine]
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
    meta["model"] = _engine_label(engine)
    answer = fields["answer"]
    if save:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("INSERT INTO chats (ts, role, content) VALUES (?, 'user', ?)", (ts, question))
        conn.execute("INSERT INTO chats (ts, role, content) VALUES (?, 'assistant', ?)", (ts, answer))
        conn.commit()
    return answer, meta
