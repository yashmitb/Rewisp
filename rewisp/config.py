"""Paths, constants, and the kill list."""

import json
from pathlib import Path

HOME = Path.home()
DATA_DIR = HOME / "Rewisp"
DB_PATH = DATA_DIR / "rewisp.db"
VAULT_DIR = DATA_DIR / "vault"
MEMORY_PATH = DATA_DIR / "memory.md"
PAUSE_FLAG = DATA_DIR / "paused"
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
}

# (browser support lives in browser.BROWSERS — Chromium family, Safari, Firefox title-only)

# Capture tuning
TICK_SECONDS = 0.5
SCROLL_SETTLE_SECONDS = 2.0
IDLE_GUARD_SECONDS = 300  # 5 min no input -> stop capturing
DEDUPE_THUMB_SIZE = 32  # NxN grayscale thumbnail for pixel diff
DEDUPE_CHANGED_FRACTION = 0.05  # <5% pixels changed -> discard
DEDUPE_PIXEL_DELTA = 24  # per-pixel gray delta (0-255) counted as "changed"
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
    "Messages",
    "WhatsApp",
    "1Password",
    "1Password 7",
    "Bitwarden",
    "KeePassXC",
    "Keychain Access",
]

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
    TOKEN_PATH.write_text(tok)
    TOKEN_PATH.chmod(0o600)
    return tok
