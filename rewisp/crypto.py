"""Database encryption at rest, and where the key lives.

Rewisp holds months of everything you have read. Until now the only thing between
that file and a plaintext read was FileVault plus directory permissions — which is
real protection, but it evaporates the moment the file leaves the machine: a
backup, a Time Machine snapshot, a synced folder, a disk imaged after a theft.

The database is now SQLCipher (AES-256, 256k KDF iterations), so the file is
meaningless without the key.

**Where the key lives, and what that honestly buys.**

The capture daemon has to run unattended — it starts at login and must work before
you have touched anything — so the key is fetched from the login Keychain without
a prompt. That protects the file *at rest*: a stolen disk, a copied database, a
backup, another account on the same Mac.

It does **not** protect against a process already running as you. Such a process
can read the same Keychain item, or simply ask the local API. Gating the key
behind Touch ID would not fix that either, because the daemon still has to hold
the key to keep capturing; it would only add a hole in the timeline after every
reboot. Pretending otherwise would be the dishonest version of this feature.

**Why the key is read through /usr/bin/security rather than the Security
framework.** Keychain ACLs bind to the calling binary's code identity, and Rewisp
is ad-hoc signed, so that identity changes on every release. Binding the item to
our own binary would mean a permission prompt — or a denial — after each update,
which is precisely the failure that made Screen Recording so painful. `security`
is Apple-signed and stable, so the ACL never goes stale.

Everything degrades safely: no SQLCipher, no Keychain, or any error at all, and
Rewisp falls back to the plaintext database it has always used. Encryption must
never be the reason someone loses their memory.
"""

import logging
import secrets
import subprocess

log = logging.getLogger("rewisp")

SERVICE = "Rewisp Database Key"
ACCOUNT = "rewisp-db"
_SECURITY = "/usr/bin/security"

_cached_key: str | None = None


def sqlcipher_available() -> bool:
    """True when the bundled runtime can open encrypted databases."""
    try:
        import sqlcipher3  # noqa: F401
    except ImportError:
        return False
    return True


def _keychain_get() -> str | None:
    try:
        p = subprocess.run(
            [_SECURITY, "find-generic-password", "-a", ACCOUNT, "-s", SERVICE, "-w"],
            capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    key = (p.stdout or "").strip()
    return key if p.returncode == 0 and key else None


def _keychain_set(key: str) -> bool:
    try:
        p = subprocess.run(
            [_SECURITY, "add-generic-password", "-a", ACCOUNT, "-s", SERVICE,
             "-w", key, "-U",
             # Available after first unlock so the daemon can start at login,
             # and never synced to iCloud or another device.
             "-T", _SECURITY],
            capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return False
    return p.returncode == 0


def get_key(create: bool = True) -> str | None:
    """The database key, creating one on first use.

    256 bits from `secrets`, hex-encoded. Returns None when the Keychain is
    unavailable, which is a signal to stay on the plaintext database rather than
    an error — a machine that cannot store a key must still be able to remember.
    """
    global _cached_key
    if _cached_key:
        return _cached_key

    key = _keychain_get()
    if key:
        _cached_key = key
        return key
    if not create:
        return None

    key = secrets.token_hex(32)
    if not _keychain_set(key):
        log.warning("encryption: couldn't store a key in the Keychain — "
                    "staying on the unencrypted database")
        return None
    # Read it back: a key we cannot retrieve later is worse than none at all,
    # because we would encrypt the database and then be unable to open it.
    check = _keychain_get()
    if check != key:
        log.error("encryption: key did not survive a Keychain round trip — "
                  "refusing to encrypt")
        return None
    _cached_key = key
    log.info("encryption: created a new database key")
    return key


def forget_cached_key() -> None:
    """Drop the in-process copy (used by tests and after a key change)."""
    global _cached_key
    _cached_key = None


def delete_key() -> bool:
    """Remove the key. Only meaningful alongside deleting the database."""
    forget_cached_key()
    try:
        p = subprocess.run(
            [_SECURITY, "delete-generic-password", "-a", ACCOUNT, "-s", SERVICE],
            capture_output=True, text=True, timeout=15)
        return p.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def is_encrypted(path) -> bool:
    """Whether a database file on disk is encrypted.

    A plaintext SQLite file always begins with the 16-byte magic string; an
    encrypted one begins with ciphertext. Checking the header means never having
    to guess, and never having to try a key against a file to find out.
    """
    import pathlib
    p = pathlib.Path(path)
    try:
        if not p.exists() or p.stat().st_size == 0:
            return False
        return p.read_bytes()[:15] != b"SQLite format 3"
    except OSError:
        return False
