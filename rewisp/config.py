"""Paths, constants, and the kill list."""

import json
import os
from pathlib import Path

HOME = Path.home()
DATA_DIR = HOME / "Rewisp"
DB_PATH = DATA_DIR / "rewisp.db"
VAULT_DIR = DATA_DIR / "vault"
MEMORY_PATH = DATA_DIR / "memory.md"
PAUSE_FLAG = DATA_DIR / "paused"


def pause_until() -> float | None:
    """Epoch seconds the pause expires, or None for an indefinite pause."""
    try:
        raw = PAUSE_FLAG.read_text().strip()
    except OSError:
        return None
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def is_paused() -> bool:
    """True while capture is paused, expiring a timed pause automatically.

    A pause with no end was the only kind available, which quietly made "pause
    while I do something sensitive" and "stop recording my life" the same
    action. People asked for a timed version precisely because the indefinite
    one is easy to set and easy to forget, and a forgotten pause looks exactly
    like a broken app: no wisps, no error, no explanation.

    Checked here rather than by a timer so it stays correct across sleep,
    restarts, and a daemon that was not running when the deadline passed.
    """
    if not PAUSE_FLAG.exists():
        return False
    until = pause_until()
    if until is None:
        return True                      # indefinite
    import time as _time
    if _time.time() >= until:
        PAUSE_FLAG.unlink(missing_ok=True)   # expired: resume on its own
        return False
    return True
KILL_LIST_PATH = DATA_DIR / "killlist.json"
LOG_PATH = DATA_DIR / "daemon.log"
TOKEN_PATH = DATA_DIR / ".api_token"  # shared secret for the localhost API
SETTINGS_PATH = DATA_DIR / "settings.json"

# engine: "auto" tries claude -> codex (ChatGPT Plus) -> ollama (free, local)
DEFAULT_SETTINGS = {
    "engine": "auto",                # auto | claude | codex | gemini | custom | local | ollama
    "disabled_engines": [],          # engines to skip in "auto" (e.g. ["claude"] to ignore Claude)
    "ollama_model": "llama3.1:8b",   # digest needs a long context window
    "gemini_api_key": "",            # free key from aistudio.google.com/apikey
    "gemini_model": "gemini-2.5-flash",
    # Any paid OpenAI-compatible API the user already has (OpenAI, DeepSeek, Groq,
    # OpenRouter, Mistral…). Never billed unless the user explicitly configures it.
    "custom_api": {"base_url": "", "api_key": "", "model": "", "label": ""},
    # Local MLX model: chosen id from localmodel.MODELS; repo overrides the default.
    "local_model": "",
    "local_model_repo": "",
    "digest_hour": 21,               # local hour the digest becomes due
    "digest_interval_days": 1,       # 1 = nightly, 2 = every other day, 7 = weekly
    # Proactive nudges (Déjà Vu / Delta / Promises). Off by default — opt in, then
    # tune. Detection is fully local (embeddings); nudges never make a cloud call.
    "nudges_enabled": False,
    "nudge_max_per_day": 3,
    "nudge_similarity": 0.82,        # cosine bar for a Déjà Vu match
    # MCP server: external agents can query screen memory; the Vault (identity
    # documents) stays out unless explicitly opted in.
    "mcp_expose_vault": False,
}

# (browser support lives in browser.BROWSERS — Chromium family, Safari, Firefox title-only)

# Capture tuning
TICK_SECONDS = 0.5
SCROLL_SETTLE_SECONDS = 2.0
IDLE_GUARD_SECONDS = 300  # 5 min no input -> stop capturing
DEDUPE_THUMB_SIZE = 32  # NxN grayscale thumbnail for pixel diff
DEDUPE_CHANGED_FRACTION = 0.05  # <5% pixels changed -> discard
DEDUPE_PIXEL_DELTA = 24  # per-pixel gray delta (0-255) counted as "changed"
# Height of the macOS menu bar in logical points. Text sitting inside it is
# never content — the app name, its menus, the clock, the battery — and it
# appeared in 100% of 500 sampled captures, costing database space, prompt room,
# and search precision ("File Edit View Window Help" matches everything and
# distinguishes nothing). Converted to a normalized cutoff per frame, because
# the bar's share of the screen differs by display.
OCR_MENUBAR_POINTS = 26

# macOS 26's document recogniser, via the bundled Swift helper (ui/RewispOCR.swift,
# shipped as Resources/rewisp-ocr). Default OFF so it can be A/B'd on real captures
# before it becomes the default.
#
# The pyobjc VNRecognizeDocumentsRequest was a dead end: its `blocks` array is a
# HIERARCHY — the same text at word, line AND paragraph granularity at once — so
# consuming it flat rendered "San  San diego  San diego  diego" (130 doubled pairs
# vs 6 for the tiled path), and selecting a single granularity needs Swift value
# types pyobjc cannot bridge.
#
# The NEW Swift-only Vision API (RecognizeDocumentsRequest, DocumentObservation.
# Container) sidesteps that: paragraph.lines is single-granularity. Probed on live
# screens — 0 doubled pairs, geometry intact (NormalizedRect, bottom-left origin,
# same convention as the old engine), so the menu-bar cutoff and reading-order
# assembly are reused unchanged. It cannot run in the Python daemon (Swift-only),
# so screen.py encodes the in-memory CGImage to PNG and pipes it to the helper.
# Any failure (missing binary, pre-26 macOS, decode error) falls back to the
# current tiled path — a capture is never lost to it.
OCR_USE_DOCUMENTS = False

# Override the helper binary path (dev/testing). Empty = locate it in the bundle.
OCR_HELPER_BIN = os.environ.get("REWISP_OCR_BIN", "")

# Purge validated card numbers and SSNs from captured text before storing or
# embedding it. On by default — a privacy backstop for PII that leaks onto
# ordinary screens the kill list doesn't cover.
REDACT_PII = True

# Shadow A/B: when on, every capture runs BOTH the tiled engine (stored, as today)
# and the Swift document engine, logging metrics only — no screen text — to
# OCR_AB_LOG. It's how we prove the document engine actually wins on real screens
# before flipping OCR_USE_DOCUMENTS on. Off by default; adds the cost of a second
# OCR per capture while enabled.
OCR_SHADOW_AB = os.environ.get("REWISP_OCR_SHADOW", "") == "1"
OCR_AB_LOG = DATA_DIR / "ocr_ab.jsonl"

MAX_OCR_CHARS = 25_000  # dense pages hit 10k and got truncated mid-content
OCR_TILING = True        # second OCR pass over 2x2 overlapping tiles for small text
OCR_TILE_MIN_WIDTH = 1600  # skip tiling for small frames — whole pass suffices
OCR_TILE_OVERLAP = 0.08  # fraction of overlap between tiles so seam text isn't cut
URL_POLL_SECONDS = 2.0  # throttle AppleScript URL queries — each osascript spawn
                        # costs ~130ms, so 1s polling ate ~13% of a core while browsing
HEARTBEAT_SECONDS = 60  # periodic capture when no trigger fired; dedupe drops unchanged screens

RETENTION_DAYS = 183  # ~6 months for captures and chats

# Semantic memory: local static-embedding model (model2vec, pure numpy, ~0.1ms).
# Retrieval merges FTS keyword rank with vector-similarity rank via RRF.
EMBED_MODEL = "minishlab/potion-retrieval-32M"  # 512-dim, retrieval-tuned
RRF_K = 60          # reciprocal-rank-fusion constant (standard default)
RRF_POOL = 40       # top-k pulled from each of FTS and vector before fusion

DEFAULT_KILL_APPS = [
    # Video calls. Not only your own privacy: when someone screen-shares a
    # document with you, capturing it stores THEIR confidential material in your
    # database, and they never agreed to that. Asked for on launch day, and the
    # right default regardless.
    "zoom.us",
    "Microsoft Teams",
    "Webex",
    "FaceTime",
    "Discord",
    "Slack Call",
    "Messages",
    "WhatsApp",
    "1Password",
    "1Password 7",
    "Bitwarden",
    "KeePassXC",
    "Keychain Access",
    # Exam proctoring browser — capturing during a locked-down exam is a
    # privacy + academic-integrity hazard. Found 29 live captures of it.
    "LockDown Browser",
]

# Frontmost "apps" that aren't real content: the Dock (a click on it makes the
# whole desktop the capture, misattributed), Mission Control, the wallpaper.
# Live data: 201 junk desktop captures in one week attributed to "Dock".
CAPTURE_SKIP_APPS = {"Dock", "Mission Control", "WindowManager", "Window Server"}

# A capture with almost no text is a video frame's subtitles or an empty screen —
# 78 live rows were fragments like "Your honor,". Not worth remembering.
MIN_CAPTURE_CHARS = 40

DEFAULT_KILL_URL_PATTERNS = [
    # substring match against the active URL, lowercased
    "chase.com", "bankofamerica.com", "wellsfargo.com", "citi.com",
    "capitalone.com", "usbank.com", "schwab.com", "fidelity.com",
    "vanguard.com", "robinhood.com", "wealthfront.com", "betterment.com",
    "paypal.com", "venmo.com", "coinbase.com", "kraken.com",
    "americanexpress.com", "discover.com", "sofi.com", "ally.com",
]

# Dia exposes no incognito flag via AppleScript; detect by window-title keywords.
PRIVATE_WINDOW_KEYWORDS = ["incognito", "private browsing", "(private)"]


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        DATA_DIR.chmod(0o700)  # screen history is for this user's eyes only
        VAULT_DIR.chmod(0o700)
    except OSError:
        pass
    # And the files themselves. The 0700 directory is the real barrier, but the
    # contents were left 0644 by SQLite and by plain writes — so anything that
    # ever escapes the directory (a copy, a backup, a restore into a different
    # location, a sync client) carries world-readable permissions with it.
    # Defence in depth costs nothing here.
    for f in (DB_PATH, MEMORY_PATH, SETTINGS_PATH):
        try:
            if f.exists():
                f.chmod(0o600)
        except OSError:
            pass
    # launchd recreates its stderr files 0644 on every boot; the 0700 directory
    # is the real barrier, but there is no reason to leave them loose.
    for name in ("com.rewisp.daemon.err", "com.rewisp.digest.err"):
        try:
            f = DATA_DIR / name
            if f.exists():
                f.chmod(0o600)
        except OSError:
            pass
    # SQLite's sidecars are recreated on demand and inherit the same exposure.
    for suffix in ("-wal", "-shm"):
        side = DB_PATH.with_name(DB_PATH.name + suffix)
        try:
            if side.exists():
                side.chmod(0o600)
        except OSError:
            pass


def load_user_kill_list() -> dict:
    """The user's own additions only (killlist.json). Defaults are always merged on top."""
    if KILL_LIST_PATH.exists():
        try:
            user = json.loads(KILL_LIST_PATH.read_text())
            return {"apps": list(user.get("apps", [])),
                    "url_patterns": [p.lower() for p in user.get("url_patterns", [])]}
        except (json.JSONDecodeError, OSError):
            pass
    return {"apps": [], "url_patterns": []}


def save_user_kill_list(apps: list[str], url_patterns: list[str]) -> None:
    """Write the user's additions. Defaults can never be removed — privacy floor."""
    ensure_dirs()
    KILL_LIST_PATH.write_text(json.dumps(
        {"apps": sorted(set(apps)), "url_patterns": sorted({p.lower() for p in url_patterns})},
        indent=2))


def load_kill_list() -> dict:
    """User kill list merged with defaults. File format: {"apps": [...], "url_patterns": [...]}"""
    user = load_user_kill_list()
    apps = set(DEFAULT_KILL_APPS) | set(user["apps"])
    patterns = set(DEFAULT_KILL_URL_PATTERNS) | set(user["url_patterns"])
    return {"apps": apps, "url_patterns": patterns}


def load_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    if SETTINGS_PATH.exists():
        try:
            s.update(json.loads(SETTINGS_PATH.read_text()))
        except (json.JSONDecodeError, OSError):
            pass
    return s


def save_settings(updates: dict) -> dict:
    ensure_dirs()
    s = load_settings()
    s.update({k: v for k, v in updates.items() if k in DEFAULT_SETTINGS})
    SETTINGS_PATH.write_text(json.dumps(s, indent=2))
    return s


def api_token() -> str:
    """Shared secret for the localhost API. Created on first use, mode 0600.
    Any local process could otherwise read the whole screen history."""
    import secrets
    ensure_dirs()
    if TOKEN_PATH.exists():
        tok = TOKEN_PATH.read_text().strip()
        if tok:
            return tok
    tok = secrets.token_hex(16)
    # Create with 0600 already set, rather than writing then chmod-ing. That
    # sequence leaves the secret world-readable for the moment in between, and
    # this token is the only thing standing between another process and the
    # entire screen history. O_EXCL so a pre-placed file cannot be hijacked.
    import os
    try:
        fd = os.open(TOKEN_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        # Raced with another writer; theirs is as good as ours.
        existing = TOKEN_PATH.read_text().strip()
        if existing:
            return existing
        os.chmod(TOKEN_PATH, 0o600)
        fd = os.open(TOKEN_PATH, os.O_WRONLY | os.O_TRUNC)
    with os.fdopen(fd, "w") as f:
        f.write(tok)
    return tok
