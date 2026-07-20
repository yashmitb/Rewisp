from pathlib import Path

from rewisp import ask, server


def test_cli_path_finds_codex_bundled_with_chatgpt(monkeypatch, tmp_path):
    embedded = tmp_path / "ChatGPT.app" / "Contents" / "Resources" / "codex"
    embedded.parent.mkdir(parents=True)
    embedded.write_text("#!/bin/sh\n")
    embedded.chmod(0o755)

    monkeypatch.setattr(ask.shutil, "which", lambda _name: None)
    monkeypatch.setattr(ask, "_fallback_cli_paths", lambda _name: (embedded,))

    assert ask.cli_path("codex") == str(embedded)


def test_engine_availability_uses_same_cli_resolution_as_calls(monkeypatch):
    monkeypatch.setattr(
        ask, "cli_path", lambda name: "/Applications/ChatGPT.app/codex" if name == "codex" else None
    )
    monkeypatch.setattr(server.config, "load_settings", lambda: {})

    available = server._engine_availability()

    assert available["codex"] is True
