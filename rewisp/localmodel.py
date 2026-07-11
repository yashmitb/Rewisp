"""Local LLM engine via MLX (Apple's native runtime — faster and lighter than
llama.cpp on Apple Silicon). Handles the model catalog, first-run download with
progress, delete / re-download, and the on-demand mlx_lm server.

Nothing is bundled in the DMG — the model is chosen for the user's hardware and
downloaded on first use, cached under ~/Rewisp/models. Fully local, unlimited,
offline, private. Users can skip it entirely and stay on Apple on-device.
"""

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from . import config

# MLX 4-bit quants. `gb` = rough on-disk size; `min_ram_gb` = don't auto-pick
# below this. Repos are the intended targets and are overridable in settings
# (settings["local_model_repo"]) in case a name changes upstream.
MODELS = {
    "qwen3.5-9b": {
        "repo": "mlx-community/Qwen3.5-9B-MLX-4bit",
        "label": "Qwen 3.5 9B", "gb": 6.0, "min_ram_gb": 32, "tier": 3,
        "note": "Best local reasoning & summaries. For 32 GB+ Macs.",
    },
    "gemma4-e4b": {
        "repo": "mlx-community/gemma-4-e4b-it-4bit",
        "label": "Gemma 4 E4B", "gb": 4.5, "min_ram_gb": 16, "tier": 2,
        "note": "Best at screen text / OCR extraction. Fast. Great default.",
    },
    "qwen3.5-4b": {
        "repo": "mlx-community/Qwen3.5-4B-MLX-4bit",
        "label": "Qwen 3.5 4B", "gb": 2.5, "min_ram_gb": 8, "tier": 1,
        "note": "Light, low-RAM — strong for its size. Runs on 8 GB Macs.",
    },
}

PORT = 11435
MODELS_DIR = config.DATA_DIR / "models"
# MLX runs in its own venv: mlx-lm needs transformers < 5, but the daemon ships
# transformers 5.x. Isolating it avoids downgrading the daemon's dependencies.
VENV_DIR = config.DATA_DIR / "mlxenv"
_SERVER_PID = config.DATA_DIR / ".mlx_server.pid"


def _venv_python() -> Path:
    return VENV_DIR / "bin" / "python"

# Download progress, polled by the UI via /local/status.
_dl = {"running": False, "model": None, "pct": 0, "error": None, "done": False}


def _hf_env() -> dict:
    """Keep all downloads inside ~/Rewisp/models so delete is contained."""
    env = dict(os.environ)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    env["HF_HOME"] = str(MODELS_DIR)
    env["HF_HUB_DISABLE_TELEMETRY"] = "1"
    return env


def mlx_installed() -> bool:
    py = _venv_python()
    if not py.exists():
        return False
    try:
        r = subprocess.run([str(py), "-c", "import mlx_lm"],
                           capture_output=True, timeout=60)
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def ensure_mlx() -> tuple[bool, str | None]:
    """Create a dedicated venv and install the MLX runtime into it. Heavy
    (~hundreds of MB) but one-time; the user installs nothing separately, and the
    daemon's own dependencies are left alone."""
    if mlx_installed():
        return True, None
    try:
        import sys
        if not _venv_python().exists():
            subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)],
                           check=True, timeout=180)
        py = str(_venv_python())
        subprocess.run([py, "-m", "pip", "install", "--quiet", "--upgrade", "pip"],
                       timeout=300)
        # mlx-lm 0.31.3 supports the 2026 models (gemma4, qwen3.5) but crashes on
        # transformers 5.10+ (register() regression) and older mlx-lm doesn't know
        # gemma4. transformers 5.0–5.9 is the window that both imports and loads them.
        subprocess.run([py, "-m", "pip", "install", "--quiet",
                        "mlx-lm==0.31.3", "transformers>=5.0,<5.10", "huggingface_hub"],
                       check=True, timeout=2400)
        return (True, None) if mlx_installed() else (False, "mlx-lm install did not take")
    except subprocess.CalledProcessError as e:
        return False, f"MLX runtime install failed: {str(e)[:150]}"
    except Exception as e:  # noqa: BLE001
        return False, f"Could not install MLX runtime: {str(e)[:150]}"


def _repo_for(model_id: str) -> str:
    s = config.load_settings()
    if s.get("local_model_repo") and s.get("local_model") == model_id:
        return s["local_model_repo"]
    return MODELS[model_id]["repo"]


def _cache_dir_for(repo: str) -> Path:
    return MODELS_DIR / "hub" / ("models--" + repo.replace("/", "--"))


def installed_models() -> list[str]:
    return [mid for mid in MODELS
            if _cache_dir_for(_repo_for(mid)).exists()]


def _dir_size_gb(p: Path) -> float:
    total = 0
    for root, _dirs, files in os.walk(p):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                pass
    return total / (1024 ** 3)


def download_async(model_id: str) -> dict:
    if model_id not in MODELS:
        return {"started": False, "error": "unknown model"}
    if _dl["running"]:
        return {"started": False, "error": "a download is already running"}
    _dl.update(running=True, model=model_id, pct=0, error=None, done=False)

    def _work():
        try:
            ok, err = ensure_mlx()
            if not ok:
                raise RuntimeError(err)
            repo = _repo_for(model_id)
            target = _cache_dir_for(repo)
            expected = MODELS[model_id]["gb"]
            stop = threading.Event()

            def _poll():  # estimate % from bytes-on-disk vs expected size
                while not stop.is_set():
                    if target.exists():
                        pct = min(int(_dir_size_gb(target) / expected * 100), 99)
                        _dl["pct"] = max(_dl["pct"], pct)
                    time.sleep(1.0)

            poller = threading.Thread(target=_poll, daemon=True)
            poller.start()
            # snapshot_download pulls the whole repo into HF_HOME cache.
            subprocess.run(
                [str(_venv_python()), "-c",
                 "from huggingface_hub import snapshot_download;"
                 f"snapshot_download('{repo}')"],
                env=_hf_env(), check=True, timeout=7200)
            stop.set()
            _dl.update(pct=100, done=True)
        except Exception as e:  # noqa: BLE001
            _dl["error"] = str(e)[:200]
        finally:
            _dl["running"] = False

    threading.Thread(target=_work, name="rewisp-model-dl", daemon=True).start()
    return {"started": True}


def download_status() -> dict:
    return dict(_dl)


def delete_model(model_id: str) -> dict:
    if model_id not in MODELS:
        return {"error": "unknown model"}
    stop_server()  # can't delete a model the server has open
    target = _cache_dir_for(_repo_for(model_id))
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    return {"deleted": model_id, "installed": installed_models()}


# ---- server lifecycle -------------------------------------------------------

def server_running() -> bool:
    if not _SERVER_PID.exists():
        return False
    try:
        pid = int(_SERVER_PID.read_text().strip())
        os.kill(pid, 0)  # signal 0 = existence check
        return True
    except (ValueError, OSError):
        return False


def ensure_server(model_id: str) -> tuple[bool, str | None]:
    """Start the mlx_lm OpenAI-compatible server for `model_id` if not already up."""
    if server_running():
        return True, None
    if model_id not in installed_models():
        return False, "model not downloaded yet"
    repo = _repo_for(model_id)
    try:
        proc = subprocess.Popen(
            [str(_venv_python()), "-m", "mlx_lm", "server",
             "--model", repo, "--host", "127.0.0.1", "--port", str(PORT)],
            env=_hf_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:  # noqa: BLE001
        return False, f"could not start MLX server: {str(e)[:150]}"
    _SERVER_PID.write_text(str(proc.pid))
    # wait for the port to answer — first cold load of a multi-GB model into
    # unified memory can take a while.
    import urllib.request
    for _ in range(180):
        if proc.poll() is not None:  # server died on startup
            return False, "MLX server exited on startup (check the model is supported)"
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/v1/models", timeout=1)
            return True, None
        except OSError:
            time.sleep(1.0)
    return False, "MLX server did not come up in time"


def stop_server() -> None:
    if not _SERVER_PID.exists():
        return
    try:
        os.kill(int(_SERVER_PID.read_text().strip()), 15)
    except (ValueError, OSError):
        pass
    _SERVER_PID.unlink(missing_ok=True)


def active_model() -> str | None:
    """The model the local engine will use: the user's choice if installed, else
    the largest installed one."""
    s = config.load_settings()
    chosen = s.get("local_model")
    inst = installed_models()
    if chosen in inst:
        return chosen
    if inst:
        return sorted(inst, key=lambda m: -MODELS[m]["tier"])[0]
    return None
