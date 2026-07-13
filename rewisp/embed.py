"""Local text embeddings for semantic (meaning-based) retrieval.

Uses model2vec static embeddings (potion-retrieval-32M) — pure-numpy inference,
no torch, ~0.1 ms per short text. Deliberately lightweight so it can run inside
the long-lived capture daemon without dragging a heavy ML runtime into it.

Everything here is fail-safe: if the model can't load (offline first run, package
missing, whatever), `available()` returns False and callers fall back to FTS-only
retrieval. Semantic search is an enhancement, never a hard dependency.
"""

import logging
import threading

import numpy as np

from . import config

log = logging.getLogger("rewisp")

DIM = 512  # potion-retrieval-32M output dimension

_model = None
_tried = False
_lock = threading.Lock()


def _load():
    """Load the static model once per process. Returns the model or None.

    Guarded so a failure is logged a single time and never retried in a tight
    loop (the daemon calls embed() on every capture)."""
    global _model, _tried
    if _model is not None or _tried:
        return _model
    with _lock:
        if _model is not None or _tried:
            return _model
        _tried = True
        try:
            from model2vec import StaticModel
            _model = StaticModel.from_pretrained(config.EMBED_MODEL)
            log.info("embed: loaded %s (dim=%d)", config.EMBED_MODEL, DIM)
        except Exception as e:  # noqa: BLE001 — offline / not installed / anything
            log.warning("embed: unavailable (%s); semantic search disabled, FTS only", e)
            _model = None
    return _model


def available() -> bool:
    return _load() is not None


def embed(text: str) -> bytes | None:
    """Embed one text -> normalized float32 vector as bytes (for a BLOB column).
    Returns None if the model is unavailable or the text is empty."""
    text = (text or "").strip()
    if not text:
        return None
    m = _load()
    if m is None:
        return None
    try:
        v = m.encode([text[:8000]])[0].astype(np.float32)
        n = np.linalg.norm(v)
        if n > 0:
            v = v / n
        return v.tobytes()
    except Exception as e:  # noqa: BLE001
        log.debug("embed failed: %s", e)
        return None


def embed_vec(text: str) -> "np.ndarray | None":
    """Same as embed() but returns the numpy vector (for query-side use)."""
    b = embed(text)
    return np.frombuffer(b, dtype=np.float32) if b is not None else None


def to_vec(blob: bytes) -> "np.ndarray":
    return np.frombuffer(blob, dtype=np.float32)
