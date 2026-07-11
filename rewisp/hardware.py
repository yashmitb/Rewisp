"""Detect this Mac's capabilities and recommend the best local model it can run
well. Apple Silicon shares memory between CPU and GPU, so unified RAM is the real
gate; chip generation nudges the pick for speed."""

import re
import shutil
import subprocess


def _sysctl(key: str) -> str:
    # Absolute path: the daemon runs under launchd with a stripped PATH, where a
    # bare "sysctl" isn't found and every probe would silently read empty.
    binary = shutil.which("sysctl") or "/usr/sbin/sysctl"
    try:
        return subprocess.run([binary, "-n", key], capture_output=True,
                              text=True, timeout=5).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def ram_gb() -> float:
    raw = _sysctl("hw.memsize")
    try:
        return round(int(raw) / (1024 ** 3), 1)
    except ValueError:
        return 0.0


def chip() -> str:
    # "Apple M3 Pro" etc. Falls back to hw.model on Intel.
    return _sysctl("machdep.cpu.brand_string") or _sysctl("hw.model")


def chip_generation() -> int:
    """M1->1, M2->2 … 0 if unknown / Intel. Used only as a small speed nudge."""
    m = re.search(r"Apple M(\d+)", chip())
    return int(m.group(1)) if m else 0


def is_apple_silicon() -> bool:
    return _sysctl("hw.optional.arm64") == "1" or "Apple M" in chip()


def free_disk_gb(path: str = None) -> float:
    import os
    from . import config
    target = path or str(config.DATA_DIR)
    try:
        st = os.statvfs(target)
        return round(st.f_bavail * st.f_frsize / (1024 ** 3), 1)
    except OSError:
        return 0.0


def probe() -> dict:
    return {
        "ram_gb": ram_gb(),
        "chip": chip(),
        "chip_generation": chip_generation(),
        "apple_silicon": is_apple_silicon(),
        "free_disk_gb": free_disk_gb(),
    }


def recommend(models: dict) -> dict:
    """Pick the best model whose min_ram fits, leaving headroom for the OS + apps.
    `models` is localmodel.MODELS. Returns {model_id | None, reason, hardware}."""
    hw = probe()
    ram = hw["ram_gb"]
    disk = hw["free_disk_gb"]
    gen = hw["chip_generation"]

    if not hw["apple_silicon"]:
        return {"model": None, "reason": "Local models need Apple Silicon. Use "
                "Apple on-device or a cloud engine instead.", "hardware": hw}
    if ram and ram < 8:
        return {"model": None, "reason": f"Only {ram} GB RAM — too little for a good "
                "local model. Stick with Apple on-device or a cloud engine.",
                "hardware": hw}

    # Candidates that fit RAM, biggest first. Budget: model ~<= half of RAM.
    fits = [(mid, m) for mid, m in models.items()
            if m["min_ram_gb"] <= ram and m["gb"] <= disk]
    if not fits:
        low = "Not enough free disk for any model." if ram >= 8 else ""
        return {"model": None, "reason": low or "No suitable local model for this Mac.",
                "hardware": hw}
    fits.sort(key=lambda x: -x[1]["tier"])
    best_id, best = fits[0]
    # Old chip + big model = slow; drop one tier for responsiveness on M1/M2.
    if gen and gen <= 2 and len(fits) > 1 and best["tier"] >= 3:
        best_id, best = fits[1]
    return {"model": best_id, "reason": f"Recommended for {hw['chip']} with {ram} GB.",
            "hardware": hw}
