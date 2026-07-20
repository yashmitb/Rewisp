"""Regression tests for the bundled-Python MLX virtual environment."""

from rewisp import localmodel


def test_venv_env_removes_bundled_python_overrides(monkeypatch):
    """A child venv must discover its own stdlib and site-packages."""
    monkeypatch.setenv("PYTHONHOME", "/Applications/Rewisp.app/Contents/Resources/python")
    monkeypatch.setenv("PYTHONPATH", "/Applications/Rewisp.app/Contents/Resources/daemon")

    env = localmodel._venv_env()

    assert "PYTHONHOME" not in env
    assert "PYTHONPATH" not in env


def test_python_works_uses_sanitized_environment(monkeypatch, tmp_path):
    python = tmp_path / "python"
    python.write_text("#!/bin/sh\ntest -z \"$PYTHONHOME\" && test -z \"$PYTHONPATH\"\n")
    python.chmod(0o755)
    monkeypatch.setenv("PYTHONHOME", "/wrong/runtime")
    monkeypatch.setenv("PYTHONPATH", "/wrong/modules")

    assert localmodel._python_works(python)
