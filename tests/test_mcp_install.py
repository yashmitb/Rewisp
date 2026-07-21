"""Writing into other apps' config files.

These files belong to the user's editor. Getting this wrong does not mean Rewisp
fails to install — it means someone loses the MCP servers they had configured.
Every test here is about not doing damage.
"""

import json

import pytest

from rewisp import config, mcp


@pytest.fixture
def target(tmp_path, monkeypatch):
    p = tmp_path / ".cursor" / "mcp.json"
    monkeypatch.setitem(mcp.INSTALL_TARGETS, "cursor",
                        {"path": lambda: p, "key": "mcpServers"})
    return p


def test_creates_the_file_when_absent(target):
    res = mcp.install_for("cursor")
    assert res["ok"], res
    assert json.loads(target.read_text())["mcpServers"]["rewisp"]["command"]


def test_preserves_other_servers(target):
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"mcpServers": {
        "github": {"command": "npx", "args": ["-y", "gh-mcp"]},
        "postgres": {"command": "pg-mcp"},
    }}))
    res = mcp.install_for("cursor")
    assert res["ok"]
    cfg = json.loads(target.read_text())
    assert set(cfg["mcpServers"]) == {"github", "postgres", "rewisp"}
    assert cfg["mcpServers"]["github"]["args"] == ["-y", "gh-mcp"]
    assert res["kept"] == ["github", "postgres"]


def test_preserves_unrelated_top_level_keys(target):
    """Gemini's settings.json holds far more than MCP config."""
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"theme": "dark", "telemetry": False}))
    assert mcp.install_for("cursor")["ok"]
    cfg = json.loads(target.read_text())
    assert cfg["theme"] == "dark" and cfg["telemetry"] is False
    assert "rewisp" in cfg["mcpServers"]


def test_malformed_json_is_refused_not_overwritten(target):
    """The important one. A previous version reset to {} and destroyed
    everything the user had configured."""
    target.parent.mkdir(parents=True)
    original = '{"mcpServers": {"github": {"command": "npx"}},,, BROKEN'
    target.write_text(original)
    res = mcp.install_for("cursor")
    assert not res["ok"]
    assert target.read_text() == original, "the user's file must be untouched"
    assert "backup" in res


def test_non_object_root_is_refused(target):
    target.parent.mkdir(parents=True)
    target.write_text('["not", "an", "object"]')
    res = mcp.install_for("cursor")
    assert not res["ok"]
    assert target.read_text().startswith("[")


def test_non_object_mcpservers_is_refused(target):
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"mcpServers": "oops"}))
    res = mcp.install_for("cursor")
    assert not res["ok"]


def test_reinstall_is_idempotent(target):
    mcp.install_for("cursor")
    first = target.read_text()
    mcp.install_for("cursor")
    assert target.read_text() == first


def test_empty_file_is_treated_as_empty_config(target):
    target.parent.mkdir(parents=True)
    target.write_text("")
    assert mcp.install_for("cursor")["ok"]


def test_unknown_client_is_rejected():
    assert not mcp.install_for("emacs")["ok"]


def test_no_temp_file_left_behind(target):
    mcp.install_for("cursor")
    leftovers = list(target.parent.glob("*rewisp-tmp*"))
    assert not leftovers, leftovers


def test_config_carries_everything_needed_to_actually_start():
    """The config must be self-sufficient.

    Regression: server_entry() declared only PYTHONPATH. The bundled interpreter
    lives in RewispBackend.app while its stdlib sits in Resources/python, so
    without PYTHONHOME it died instantly with "Failed to import encodings
    module" and every client reported the same useless "Server disconnected".
    A config that cannot start the thing it configures is not a config.
    """
    import pathlib
    import sys

    from rewisp import mcp

    env = mcp.server_entry()["env"]
    assert "PYTHONPATH" in env

    exe = pathlib.Path(sys.executable)
    bundled = any((p / "Resources" / "python" / "lib").is_dir() for p in exe.parents)
    if bundled:
        assert "PYTHONHOME" in env, "bundled runtime cannot start without PYTHONHOME"
        assert (pathlib.Path(env["PYTHONHOME"]) / "lib").is_dir()

    # Never let an MCP client write bytecode into the signed bundle: that
    # invalidates the signature and macOS withdraws Screen Recording.
    assert "PYTHONPYCACHEPREFIX" in env
    assert ".app/" not in env["PYTHONPYCACHEPREFIX"]
