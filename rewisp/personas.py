"""Personas — more than one *you*, and knowing which one belongs where.

A Vault entry answers "what is my email". A person has several, and which one is
correct depends entirely on where you are: the .edu on a course site, the Gmail
on a shopping cart. Today Rewisp returns whichever line matched first, silently,
and autofill puts that in the box.

Every password manager makes you pick the identity by hand every single time,
because filling the wrong one is embarrassing in a way that a missing value is
not. Rewisp can do better than that — it already knows the site, the app, and
what you chose the last time you were here — but only by being honest about the
order of those things:

  1. **Remember per site.** You pick once; from then on that site is settled.
     This is ~100% accurate and it is the whole feature.
  2. **Offer, never assume, on a site never seen before.** A first visit is a
     guess, and a silently wrong identity in a form is the failure that would
     make nobody trust the feature again.
  3. **Always one tap to change it**, which is what makes (1) safe to rely on.

A persona is a **folder in the Vault** (`vault/school/…`). Files at the top level
belong to everyone — your resume is your resume. Nothing here invents a new
store: `vault.reindex` already walks subfolders and records relative paths, so a
persona is just the first path segment, and moving a file between personas is
something you can do in Finder without the app running.

Fully local. No model call: this is folders, string matching, and a lookup table.
"""

import logging
import pathlib
import re
from urllib.parse import urlsplit

from . import db

log = logging.getLogger("rewisp")

# The personas Rewisp knows how to propose during setup. Not a limit — any folder
# in the Vault becomes a persona — just the ones it can recognise well enough to
# suggest, and the order they're offered in.
KNOWN = {
    "school":   {"label": "School",   "symbol": "graduationcap.fill"},
    "personal": {"label": "Personal", "symbol": "house.fill"},
    "work":     {"label": "Work",     "symbol": "briefcase.fill"},
    "rewisp":   {"label": "Rewisp",   "symbol": "sparkles"},
}
# Listed first, and the default Copy value when a question has several answers.
# Personal because most forms anyone fills are shopping and accounts; it is a
# setting rather than a law.
DEFAULT_PRIMARY = "personal"


def primary(settings: dict | None = None) -> str:
    from . import config
    s = settings if settings is not None else config.load_settings()
    return (s.get("persona_primary") or DEFAULT_PRIMARY).lower()


# ── which persona a file belongs to ──────────────────────────────────────────

def persona_of(path: str) -> str | None:
    """Persona owning a Vault file, or None when it's shared.

    Paths are stored relative to the Vault root, so the first segment is the
    folder. A file sitting at the top level has no persona and is deliberately
    visible to all of them — a transcript does not become school-only just
    because school exists.
    """
    parts = str(path or "").replace("\\", "/").split("/")
    return parts[0].lower() if len(parts) > 1 and parts[0] else None


def known_personas(conn=None, paths: list[str] | None = None) -> list[str]:
    """Personas that actually exist, i.e. have at least one file. Ordered with
    the primary first, then the rest of the recognised ones, then anything the
    user invented, alphabetically.

    Takes `paths` so a caller that has already loaded the Vault can avoid asking
    again — see values_for, where re-querying between calls was a real bug.
    """
    if paths is None:
        if conn is None:
            return []
        paths = [p for (p,) in conn.execute("SELECT path FROM vault_files")]
    found = {name for p in paths if (name := persona_of(p))}
    prim = primary()
    order = [prim] + [k for k in KNOWN if k != prim]
    out = [p for p in order if p in found]
    out += sorted(found - set(out))
    return out


def clean_name(name: str) -> str:
    """A persona name that is safe to use as a folder.

    This is a security boundary, not tidiness. apply_split joins the name onto
    the Vault path, so an unsanitised "../../../tmp/evil" resolved outside the
    Vault entirely and would have moved identity documents there. Stripped to
    a single harmless path segment.
    """
    return re.sub(r"[^a-z0-9_-]", "", str(name or "").strip().lower())[:30]


def label_for(name: str) -> str:
    return KNOWN.get(name, {}).get("label") or name.replace("-", " ").title()


def _rows_for(rows, persona: str | None, shared: bool = True):
    """Partition preloaded Vault rows for one persona.

    `shared=False` restricts to the persona's own files, which is what makes it
    possible to say truthfully whose value something is. With shared included
    they come last, so a persona's own answer still wins over the common one —
    that ordering is what autofill wants, where falling back to the shared value
    is better than filling nothing.
    """
    own = [r for r in rows if persona_of(r[0]) == persona]
    if persona is None or not shared:
        return own
    return own + [r for r in rows if persona_of(r[0]) is None]


# ── answering ────────────────────────────────────────────────────────────────

def values_for(conn, question: str) -> list[dict]:
    """Every persona's answer to a personal-fact question.

    Returns [{persona, label, answer, source}] with the primary first. Answering
    "what's my email" with one address and no indication that there are three is
    the behaviour this exists to end — the ambiguity is real, so it's shown.
    """
    from . import ask, vault
    # Load the Vault ONCE. The first version queried per persona, and
    # vault_fact reindexes on entry — so the table could change underneath the
    # loop and later personas silently answered from nothing. A test caught it;
    # in production it would have looked like "school just has no email".
    try:
        vault.reindex(conn)
    except Exception:  # noqa: BLE001 — a stale index still answers
        pass
    rows = conn.execute("SELECT path, content FROM vault_files").fetchall()
    out: list[dict] = []
    seen: set[str] = set()

    # Each persona is asked about its OWN files only.
    #
    # The first version searched a persona's files PLUS the shared ones and
    # de-duplicated by answer, which quietly credited a shared value to whoever
    # happened to be listed first: a phone number that belongs to everybody
    # showed up labelled "Personal", and had the order differed it would have
    # been labelled "School". Both are wrong, and a persona feature that
    # mislabels whose value something is has failed at its one job. Shared
    # values are now asked for separately and labelled as shared.
    for name in known_personas(paths=[r[0] for r in rows]):
        hit = ask.vault_fact(conn, question, rows=_rows_for(rows, name, shared=False))
        if not hit:
            continue
        answer = (hit.get("copy_text") or hit.get("answer") or "").strip()
        if not answer or answer.lower() in seen:
            continue
        seen.add(answer.lower())
        out.append({"persona": name, "label": label_for(name), "shared": False,
                    "answer": answer, "source": hit.get("source")})

    shared = ask.vault_fact(conn, question, rows=_rows_for(rows, None))
    if shared:
        answer = (shared.get("copy_text") or shared.get("answer") or "").strip()
        if answer and answer.lower() not in seen:
            out.append({"persona": None, "label": "Everyone", "shared": True,
                        "answer": answer, "source": shared.get("source")})
    return out


# ── which persona belongs to a site ──────────────────────────────────────────

def host_of(url: str | None) -> str:
    """Bare host for a URL — the unit a persona choice is remembered against.
    Remembering per full URL would forget the moment a query string changed."""
    if not url:
        return ""
    try:
        host = urlsplit(url.strip()).netloc.split("@")[-1].split(":")[0].lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _ensure_table(conn) -> None:
    # No commit: CREATE TABLE autocommits in SQLite, and committing here ran a
    # write on every autofill lookup, which is a read.
    conn.execute("""CREATE TABLE IF NOT EXISTS site_persona (
        site TEXT PRIMARY KEY,      -- bare host, or 'app::<name>' for native apps
        persona TEXT,
        updated_at TEXT)""")


def site_key(url: str | None, app: str | None = None) -> str:
    """Identity a persona choice is stored against. Falls back to the app for a
    native window, where there is no URL but "which you" is just as ambiguous."""
    host = host_of(url)
    if host:
        return host
    return f"app::{(app or '').strip().lower()}" if app else ""


def for_site(conn, url: str | None, app: str | None = None) -> str | None:
    """The persona already settled for this site, or None if it's never been
    seen. None means OFFER — never guess and fill."""
    key = site_key(url, app)
    if not key:
        return None
    _ensure_table(conn)
    row = conn.execute("SELECT persona FROM site_persona WHERE site = ?", (key,)).fetchone()
    return row[0] if row else None


def remember_site(conn, url: str | None, persona: str, app: str | None = None) -> str:
    """Settle a site on a persona. Called when the user picks one — including
    when they *change* it, which is what makes relying on the memory safe."""
    key = site_key(url, app)
    if not key:
        return ""
    _ensure_table(conn)
    conn.execute("INSERT OR REPLACE INTO site_persona (site, persona, updated_at) "
                 "VALUES (?, ?, ?)", (key, persona.lower(), db.utcnow()))
    conn.commit()
    log.info("personas: %s is now %s", key, persona)
    return key


def forget_site(conn, url: str | None, app: str | None = None) -> bool:
    key = site_key(url, app)
    if not key:
        return False
    _ensure_table(conn)
    n = conn.execute("DELETE FROM site_persona WHERE site = ?", (key,)).rowcount
    conn.commit()
    return bool(n)


def all_sites(conn) -> list[dict]:
    """Every remembered site, newest first — so a wrong one can be found and
    changed without hunting for the page that set it."""
    _ensure_table(conn)
    return [{"site": s, "persona": p, "label": label_for(p), "updated_at": u}
            for s, p, u in conn.execute(
                "SELECT site, persona, updated_at FROM site_persona "
                "ORDER BY updated_at DESC")]


# ── setting up, from a Vault that has no personas yet ────────────────────────

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")

# Documents that belong to every persona no matter whose address is printed on
# them. Caught by a dry run against a real Vault, which wanted to file a resume,
# a portfolio and a transcript as School-only because they carry a .edu address.
# They do — as contact information. A resume is a resume: you send it from
# whichever identity you like, and locking it to one would mean the others
# silently stop being able to answer from it.
_SHARED_DOC = re.compile(
    r"\b(resume|cv|curriculum[ _-]?vitae|transcript|portfolio|links|"
    r"diploma|certificate|reference[s]?|cover[ _-]?letter)\b", re.I)

# Only the signals strong enough to propose out loud. Everything else is left to
# the user, because a wrong guess here files a document under the wrong identity
# and then quietly answers from it forever.
_HINTS = [
    (re.compile(r"@[\w.-]*\.edu\b", re.I), "school"),
    (re.compile(r"\b(ucsd|university|campus|student\s*id|transcript|canvas)\b", re.I), "school"),
    (re.compile(r"@(gmail|yahoo|outlook|hotmail|icloud|proton)\.", re.I), "personal"),
    (re.compile(r"\busers\.noreply\.github\.com\b", re.I), "rewisp"),
    # Deliberately NOT matching the word "rewisp" or "client" in file contents:
    # a portfolio that mentions the project is not a Rewisp-identity document,
    # and "client" appears in "Lunar Client". A hint that fires on a passing
    # mention files the wrong identity and then answers as the wrong person.
    (re.compile(r"\b(invoice|contract|freelance|llc|consulting)\b", re.I), "work"),
]


def _persona_of_email(addr: str) -> str | None:
    """Which persona an address belongs to, by domain. None when it says nothing."""
    a = addr.lower()
    if re.search(r"\.edu$|\.edu\b", a):
        return "school"
    if "users.noreply.github.com" in a:
        return "rewisp"
    if re.search(r"@(gmail|yahoo|outlook|hotmail|icloud|proton(mail)?)\.", a):
        return "personal"
    return None


def propose_split(conn) -> list[dict]:
    """Look at the shared Vault and suggest where each file might belong.

    Deliberately a *proposal*. Nothing is moved: filing someone's identity
    documents into the wrong bucket, unasked, would be both wrong and invisible
    — the file would simply start answering as the wrong person. Every suggestion
    carries the evidence that produced it so the user can judge it at a glance.

    The decision is driven by ADDRESSES first, because an address is the one
    thing in these files that names an identity unambiguously. Counting regex
    hits instead was the earlier mistake: two different patterns both matched the
    same .edu address, so a file holding a school address AND a personal one
    scored 2-1 for school and got confidently misfiled. If the addresses in a
    file point at more than one persona, the file is ambiguous and gets no
    suggestion at all — that is the honest answer, and the user can file it in
    two seconds.
    """
    out: list[dict] = []
    for path, content in conn.execute("SELECT path, content FROM vault_files"):
        if persona_of(path):
            continue                       # already filed
        # Underscores and hyphens are word characters, so a bare \b pattern
        # never matched "College_Resume" — normalise them to spaces first. And
        # check the opening of the document too: "latestcollegetrans.pdf" says
        # nothing in its name and "Transcript" in its first line.
        stem = re.sub(r"[_\-]+", " ", pathlib.PurePath(path).stem)
        if _SHARED_DOC.search(stem) or _SHARED_DOC.search((content or "")[:300]):
            continue                       # a resume is a resume
        text = content or ""
        emails = sorted({e for e in _EMAIL.findall(text)})
        from_email = {p for e in emails if (p := _persona_of_email(e))}
        if len(from_email) > 1:
            continue                       # two identities in one file: ambiguous
        if len(from_email) == 1:
            best = next(iter(from_email))
            evidence = [e for e in emails if _persona_of_email(e) == best][:3]
        else:
            # No address to go on. Fall back to keywords, and only when one
            # persona clearly leads — a tie is a coin flip dressed as advice.
            votes: dict[str, set[str]] = {}
            for pattern, name in _HINTS:
                for m in pattern.findall(text):
                    votes.setdefault(name, set()).add(
                        (m if isinstance(m, str) else m[0]).strip()[:60])
            if not votes:
                continue
            ranked = sorted(votes, key=lambda k: -len(votes[k]))
            best = ranked[0]
            if len(ranked) > 1 and len(votes[ranked[1]]) == len(votes[best]):
                continue
            evidence = sorted(votes[best])[:3]
        out.append({
            "path": path,
            "suggested": best,
            "label": label_for(best),
            # What convinced it. A proposal you cannot check is one you can only
            # accept on faith.
            "evidence": evidence,
            "emails": emails[:4],
        })
    return out


def apply_split(conn, moves: list[dict]) -> dict:
    """Move approved files into their persona folders and reindex.

    `moves` is [{path, persona}] straight from what the user approved. Anything
    not listed stays exactly where it is.
    """
    import shutil
    from . import config, vault

    moved, failed = [], []
    for m in moves:
        rel = str(m.get("path") or "")
        name = clean_name(m.get("persona"))
        if not rel or not name or persona_of(rel):
            continue
        root = config.VAULT_DIR.resolve()
        src = (config.VAULT_DIR / rel).resolve()
        # Same guard as /vault/delete: stay inside the Vault, no traversal.
        if not src.is_file() or src.parent != root:
            failed.append(rel)
            continue
        dest_dir = (config.VAULT_DIR / name).resolve()
        # Belt and braces on top of clean_name: whatever the name turned out to
        # be, the destination has to sit directly inside the Vault.
        if dest_dir.parent != root:
            failed.append(rel)
            continue
        dest = dest_dir / src.name
        if dest.exists():
            failed.append(rel)
            continue
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            moved.append(f"{name}/{src.name}")
        except OSError:
            failed.append(rel)
    if moved:
        # The index keys on path, so a moved file must be re-read or it keeps
        # answering as shared.
        vault.reindex(conn)
        log.info("personas: filed %d vault file(s)", len(moved))
    return {"moved": moved, "failed": failed}


def ensure_folders(conn, names: list[str]) -> list[str]:
    """Create empty persona folders so they exist to drag things into."""
    from . import config
    made = []
    for n in names:
        clean = clean_name(n)
        if not clean:
            continue
        d = config.VAULT_DIR / clean
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            made.append(clean)
    return made
