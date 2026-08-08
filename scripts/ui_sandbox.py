"""Serve a THROWAWAY Rewisp for driving the real UI against.

Points the daemon's config at a temp directory holding a copy of the Vault and
an empty database, then serves the API on a spare port. Launch the app with
REWISP_PORT set to that port and every screen works — including the flows that
move files — without the real capture daemon, database or Vault being involved.

    python3 scripts/ui_sandbox.py [port]
"""
import pathlib, shutil, sys, tempfile, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
port = int(sys.argv[1]) if len(sys.argv) > 1 else 43219

from rewisp import config
sandbox = pathlib.Path(tempfile.mkdtemp(prefix="rewisp-ui-"))
config.DATA_DIR = sandbox
config.VAULT_DIR = sandbox / "vault"
config.DB_PATH = sandbox / "rewisp.db"
config.SETTINGS_PATH = sandbox / "settings.json"
config.TOKEN_PATH = pathlib.Path.home() / "Rewisp" / ".api_token"   # reuse the app's token
config.MEMORY_PATH = sandbox / "memory.md"
config.VAULT_DIR.mkdir(parents=True)
real = pathlib.Path.home() / "Rewisp" / "vault"
if real.is_dir():
    for f in real.iterdir():
        if f.is_file() and not f.name.startswith("."):
            shutil.copy(f, config.VAULT_DIR / f.name)

from rewisp import db, server, vault
conn = db.connect()
conn.executescript(vault.VAULT_SCHEMA)
vault.reindex(conn)
conn.close()
server.PORT = port
srv = server.start()
print(f"sandbox {sandbox}\nserving on {port}", flush=True)
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass
finally:
    srv.shutdown()
    shutil.rmtree(sandbox, ignore_errors=True)
