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


def folder_personas() -> set[str]:
    """Persona folders that exist in the Vault, even while still empty.

    An empty folder is a persona the user has declared and not yet filled. Only
    counting folders that already hold a file made "Create the folders for me"
    a dead end: it made all four, said so, and the list stayed empty until the
    user opened Finder and dragged something in.
    """
    from . import config
    try:
        return {d.name.lower() for d in config.VAULT_DIR.iterdir()
                if d.is_dir() and not d.name.startswith(".")}
    except OSError:
        return set()


def known_personas(conn=None, paths: list[str] | None = None) -> list[str]:
    """Personas that exist — a folder in the Vault, filled or not. Ordered with
    the primary first, then the rest of the recognised ones, then anything the
    user invented, alphabetically.

    Takes `paths` so a caller that has already loaded the Vault can avoid asking
    again — see values_for, where re-querying between calls was a real bug.
    """
    if paths is None:
        if conn is None:
            return []
        paths = [p for (p,) in conn.execute("SELECT path FROM vault_files")]
    found = {name for p in paths if (name := persona_of(p))} | folder_personas()
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


def is_valid_persona(conn, name: str) -> bool:
    """Whether a name is a persona this Vault actually has.

    clean_name only guarantees the name is HARMLESS, not that it means anything:
    "../../etc" survives it as "etc", which the server then happily settled a
    site on. The site is stuck answering as a persona with no files, which looks
    exactly like autofill being broken. A name has to be one Rewisp offers or one
    the user has made.
    """
    return bool(name) and (name in KNOWN or name in known_personas(conn))


def label_for(name: str) -> str:
    return KNOWN.get(name, {}).get("label") or name.replace("-", " ").title()


def rows_for(conn, persona: str | None, shared: bool = True):
    """Vault rows an identity may answer from, loaded fresh.

    The public door onto `_rows_for` for callers outside this module — autofill,
    mainly, which needs a persona's own files to win and the shared ones to be
    there as a fallback rather than a competitor.
    """
    if not persona:
        return None                       # None means "the whole Vault"
    rows = conn.execute("SELECT path, content FROM vault_files").fetchall()
    return _rows_for(rows, persona, shared=shared)


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

# Native apps have no URL, so their choice is stored under a key that cannot
# collide with a hostname. It is NOT a URL and must never be parsed as one.
APP_PREFIX = "app::"


def host_of(url: str | None) -> str:
    """Bare host for a URL — the unit a persona choice is remembered against.
    Remembering per full URL would forget the moment a query string changed."""
    raw = (url or "").strip()
    if not raw:
        return ""
    if raw.lower().startswith(APP_PREFIX):
        return ""          # a native-app key, not a URL. See site_key.
    # A bare "example.com/signup" has no scheme, so urlsplit reads the whole
    # thing as a path and the site can never be settled. "//" makes it a netloc.
    if "://" not in raw and not raw.startswith("//"):
        raw = "//" + raw
    try:
        # .hostname, not netloc split on ":" — hand-splitting on the port
        # separator turns "[::1]:8080" into "[" and "app::mail" into "app".
        host = (urlsplit(raw).hostname or "").lower()
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
    return f"{APP_PREFIX}{(app or '').strip().lower()}" if app else ""


def for_site(conn, url: str | None, app: str | None = None) -> str | None:
    """The persona already settled for this site, or None if it's never been
    seen. None means OFFER — never guess and fill."""
    key = site_key(url, app)
    if not key:
        return None
    _ensure_table(conn)
    row = conn.execute("SELECT persona FROM site_persona WHERE site = ?", (key,)).fetchone()
    if not row:
        return None
    # A persona that no longer exists is not an answer. Rows written before the
    # name was validated, or a folder the user has since deleted, would otherwise
    # keep a site "settled" on an identity with nothing behind it — which reads
    # as autofill silently doing nothing. Unsettled means OFFER, which is right.
    return row[0] if is_valid_persona(conn, row[0]) else None


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


def forget_site(conn, url: str | None, app: str | None = None,
                key: str | None = None) -> bool:
    """Forget a settled site. `key` forgets the stored row EXACTLY.

    The UI lists rows by their stored key and used to hand back "https://" + key
    to forget one. That round-trip is lossy: an app row is stored as `app::mail`,
    and re-parsing it as a URL yielded the host `app`, so the delete matched
    nothing and a native app could never be un-settled from the list. Anything
    listing rows should forget by key.
    """
    key = (key or "").strip().lower() or site_key(url, app)
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


# ── splitting ONE file that holds several identities ────────────────────────
#
# The per-file model breaks on the file that matters most. A real Vault has a
# single "personal info" note holding a student id, a university address, a
# personal address, a home address and a phone number — three identities in
# eight lines. Filing that note into one folder is impossible, so it gets no
# suggestion at all, and it is precisely the file every autofill value comes
# from. Splitting has to happen at the LINE, not the file.

# Lines that name an identity without carrying an address.
_LINE_HINTS = [
    (re.compile(r"\b(pid|student\s*id|campus|university|college|major|gpa|"
                r"transcript|semester|quarter|dorm)\b", re.I), "school"),
    (re.compile(r"\bhome\s+address\b|\bpersonal\b", re.I), "personal"),
]


def classify_line(line: str) -> str | None:
    """Which persona a single line belongs to, or None for 'everyone'.

    An address decides on its own; otherwise a label word does. Anything else —
    a name, a bare phone number — is deliberately left shared, because it is
    genuinely the same for every persona and duplicating it would create two
    copies to keep in sync.
    """
    for e in _EMAIL.findall(line):
        if p := _persona_of_email(e):
            return p
    for pattern, name in _LINE_HINTS:
        if pattern.search(line):
            return name
    return None


# Only these are safe to rewrite: for anything else the indexed "content" is
# EXTRACTED text, not the bytes on disk, so writing it back destroys the file.
# Found the hard way — a sandbox run turned a 2-page PDF into a text file.
#
# Exactly the suffixes `vault.extract_text` reads verbatim off disk. It listed
# ".markdown" and ".text" too, which the indexer has never read at all — dead
# entries that quietly implied a coverage this does not have.
PLAIN_TEXT = {".md", ".txt"}
# An identity note is short. A portfolio is not: the first version happily
# shredded a 90-line CV line by line into persona folders, which is nonsense —
# a long document is a document, not a list of facts about who you are.
MAX_SPLIT_LINES = 30


def propose_line_split(conn) -> list[dict]:
    """For each shared file holding MORE THAN ONE identity, propose a per-line
    split. Returns [{path, personas, lines:[{text, persona}]}].

    Restricted to short files, and to ones whose stored content IS their bytes.
    A resume, transcript or portfolio is excluded outright: those belong to
    every persona, and chopping them up would both mangle the document and
    scatter one CV across three folders.
    """
    out = []
    for path, content in conn.execute("SELECT path, content FROM vault_files"):
        if persona_of(path) or not content:
            continue
        stem = re.sub(r"[_\-]+", " ", pathlib.PurePath(path).stem)
        if _SHARED_DOC.search(stem) or _SHARED_DOC.search(content[:300]):
            continue                      # a resume is a resume
        lines = [ln for ln in content.splitlines() if ln.strip()]
        if len(lines) > MAX_SPLIT_LINES:
            continue                      # a document, not an identity note
        assigned = [{"text": ln, "persona": classify_line(ln)} for ln in lines]
        found = {a["persona"] for a in assigned if a["persona"]}
        if len(found) < 2:
            continue                      # one identity or none: the file-level
        out.append({                      # proposal already handles it
            "path": path,
            "personas": sorted(found),
            "lines": assigned,
        })
    return out


def apply_line_split(conn, path: str, lines: list[dict]) -> dict:
    """Write each persona's lines into its own file and leave the shared ones.

    Non-destructive by construction. The original is copied to a DOT-prefixed
    name first, which `vault.reindex` skips — so the bytes survive on disk, the
    values are not duplicated into the index, and a split that turns out wrong
    costs one rename to undo. Rewriting someone's identity file in place with no
    way back is not a thing to do on a suggestion.
    """
    from . import config, vault

    root = config.VAULT_DIR.resolve()
    src = (config.VAULT_DIR / path).resolve()
    if not src.is_file() or src.parent != root:
        return {"error": "bad path"}

    by: dict[str, list[str]] = {}
    shared: list[str] = []
    for item in lines:
        text = str(item.get("text") or "")
        name = clean_name(item.get("persona") or "")
        if not text.strip():
            continue
        if name and not is_valid_persona(conn, name):
            # Same reason as remember_site: clean_name makes a name harmless,
            # not meaningful. Filing lines into a folder named after a mangled
            # traversal attempt is not something to do quietly.
            return {"error": f"no such persona: {name}"}
        (by.setdefault(name, []) if name else shared).append(text)
    if not by:
        return {"error": "nothing assigned"}

    backup = src.with_name("." + src.name + ".before-split")
    written: list[str] = []
    shared_path: str | None = None
    try:
        backup.write_bytes(src.read_bytes())
        for name, own in by.items():
            d = (config.VAULT_DIR / name).resolve()
            if d.parent != root:               # clean_name should make this
                continue                       # impossible; refuse anyway
            d.mkdir(parents=True, exist_ok=True)
            target = d / f"{src.stem}.md"
            existing = target.read_text() if target.exists() else ""
            # Appending is right — a persona file is a place values accumulate.
            # Appending a value that is ALREADY there is not: splitting the same
            # note twice (or two notes sharing a stem) left "ucsd pid A123" and
            # "ucsd pid B999" both live in one file, and the stale one answered
            # first. Only lines the file does not already hold are added.
            have = {ln.strip() for ln in existing.splitlines() if ln.strip()}
            fresh = [ln for ln in own if ln.strip() not in have]
            if not fresh and existing:
                written.append(f"{name}/{target.name}")
                continue
            body = (existing.rstrip() + "\n" if existing else "") + "\n".join(fresh) + "\n"
            target.write_text(body)
            written.append(f"{name}/{target.name}")
        # What is left is what genuinely belongs to everyone.
        #
        # Critically, the leftovers are only written back IN PLACE when the file
        # is genuinely plain text. For an .rtf or a .pdf the indexed content is
        # extracted text, and writing it back replaces the document with a
        # transcript of itself — a sandbox run destroyed a 2-page PDF exactly
        # this way. Those originals are retired to the hidden backup instead and
        # the shared lines go to a new .md, so nothing is corrupted and nothing
        # is indexed twice.
        plain = src.suffix.lower() in PLAIN_TEXT
        if plain:
            if shared:
                src.write_text("\n".join(shared) + "\n")
                shared_path = src.name
            else:
                src.unlink()
        else:
            if shared:
                # NEVER a blind write. `{stem}.md` is a name someone else's file
                # can already own — a Vault holding both `info.rtf` and `info.md`
                # had the .md silently overwritten by the .rtf's leftovers, and
                # the only backup taken was of the .rtf. That is unrelated data
                # destroyed with nothing to restore from. Take a free name.
                dest = _free_name(config.VAULT_DIR / f"{src.stem}.md")
                dest.write_text("\n".join(shared) + "\n")
                shared_path = dest.name
            src.unlink()          # bytes preserved in the dot-prefixed backup
    except OSError as e:
        return {"error": str(e)}
    vault.reindex(conn)
    log.info("personas: split %s into %s", path, written)
    return {"written": written, "shared_kept": len(shared),
            "shared_path": shared_path, "backup": backup.name}


def _free_name(path: pathlib.Path) -> pathlib.Path:
    """`path` if nothing is there, otherwise the first `stem-shared[-N]` that is
    free. Writing to a name already in use is how an unrelated file dies."""
    if not path.exists():
        return path
    for n in range(2, 100):
        alt = path.with_name(f"{path.stem}-shared{'' if n == 2 else f'-{n}'}{path.suffix}")
        if not alt.exists():
            return alt
    raise OSError(f"no free name for {path.name}")
