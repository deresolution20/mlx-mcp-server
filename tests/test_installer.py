# tests/test_installer.py
import json
import os
import pytest
import stat
from pathlib import Path
from mlx_mcp_server.installer import (
    install,
    install_commands,
    install_scripts,
    _claude_desktop_config_path,
    _claude_code_config_path,
    _bundled_commands_dir,
    _bundled_scripts_dir,
)


def test_claude_code_config_path():
    path = _claude_code_config_path()
    assert path == Path.home() / ".claude" / "settings.json"


def test_install_creates_config_file(tmp_path, monkeypatch):
    config_file = tmp_path / "claude_desktop_config.json"
    monkeypatch.setattr("mlx_mcp_server.installer._claude_desktop_config_path", lambda: config_file)

    install(claude_code=False, base_url="http://localhost:8080", model="", api_key="", dry_run=False)

    assert config_file.exists()
    data = json.loads(config_file.read_text())
    assert data["mcpServers"]["mlx"]["command"] == "mlx-mcp-server"
    assert data["mcpServers"]["mlx"]["env"]["MLX_BASE_URL"] == "http://localhost:8080"


def test_install_preserves_existing_servers(tmp_path, monkeypatch):
    config_file = tmp_path / "claude_desktop_config.json"
    config_file.write_text(json.dumps({
        "mcpServers": {
            "other-server": {"command": "other-cmd"}
        }
    }))
    monkeypatch.setattr("mlx_mcp_server.installer._claude_desktop_config_path", lambda: config_file)

    install(claude_code=False, base_url="http://localhost:8080", model="", api_key="", dry_run=False)

    data = json.loads(config_file.read_text())
    assert "other-server" in data["mcpServers"]
    assert "mlx" in data["mcpServers"]


def test_install_updates_existing_mlx_entry(tmp_path, monkeypatch):
    config_file = tmp_path / "claude_desktop_config.json"
    config_file.write_text(json.dumps({
        "mcpServers": {
            "mlx": {"command": "old-cmd", "env": {"MLX_BASE_URL": "http://old:1234"}}
        }
    }))
    monkeypatch.setattr("mlx_mcp_server.installer._claude_desktop_config_path", lambda: config_file)

    install(claude_code=False, base_url="http://localhost:8080", model="mistral", api_key="", dry_run=False)

    data = json.loads(config_file.read_text())
    assert data["mcpServers"]["mlx"]["env"]["MLX_BASE_URL"] == "http://localhost:8080"
    assert data["mcpServers"]["mlx"]["env"]["MLX_DEFAULT_MODEL"] == "mistral"


def test_install_dry_run_does_not_write(tmp_path, monkeypatch, capsys):
    config_file = tmp_path / "claude_desktop_config.json"
    monkeypatch.setattr("mlx_mcp_server.installer._claude_desktop_config_path", lambda: config_file)

    install(claude_code=False, base_url="http://localhost:8080", model="", api_key="", dry_run=True)

    assert not config_file.exists()
    captured = capsys.readouterr()
    assert "mlx-mcp-server" in captured.out


def test_install_claude_code(tmp_path, monkeypatch):
    config_file = tmp_path / "settings.json"
    monkeypatch.setattr("mlx_mcp_server.installer._claude_code_config_path", lambda: config_file)

    install(claude_code=True, base_url="http://localhost:8080", model="", api_key="", dry_run=False)

    data = json.loads(config_file.read_text())
    assert "mlx" in data["mcpServers"]


def test_install_omits_default_model_when_empty(tmp_path, monkeypatch):
    config_file = tmp_path / "claude_desktop_config.json"
    monkeypatch.setattr("mlx_mcp_server.installer._claude_desktop_config_path", lambda: config_file)

    install(claude_code=False, base_url="http://localhost:8080", model="", api_key="", dry_run=False)

    data = json.loads(config_file.read_text())
    assert "MLX_DEFAULT_MODEL" not in data["mcpServers"]["mlx"]["env"]


def test_install_with_api_key(tmp_path, monkeypatch):
    config_file = tmp_path / "claude_desktop_config.json"
    monkeypatch.setattr("mlx_mcp_server.installer._claude_desktop_config_path", lambda: config_file)

    install(claude_code=False, base_url="http://localhost:8000", model="", api_key="my-secret-key", dry_run=False)

    data = json.loads(config_file.read_text())
    assert data["mcpServers"]["mlx"]["env"]["MLX_API_KEY"] == "my-secret-key"
    assert data["mcpServers"]["mlx"]["env"]["MLX_BASE_URL"] == "http://localhost:8000"


def test_install_without_api_key_omits_key(tmp_path, monkeypatch):
    config_file = tmp_path / "claude_desktop_config.json"
    monkeypatch.setattr("mlx_mcp_server.installer._claude_desktop_config_path", lambda: config_file)

    install(claude_code=False, base_url="http://localhost:8080", model="", api_key="", dry_run=False)

    data = json.loads(config_file.read_text())
    assert "MLX_API_KEY" not in data["mcpServers"]["mlx"]["env"]


# ── install_commands ──────────────────────────────────────────────────────────

@pytest.fixture
def fake_commands_dir(tmp_path):
    """Temporary directory containing fake bundled commands."""
    src = tmp_path / "bundled_commands"
    src.mkdir()
    (src / "switch-model.md").write_text("Switch model command")
    (src / "big-model.md").write_text("Big model command")
    return src


@pytest.fixture
def fake_scripts_dir(tmp_path):
    """Temporary directory containing fake bundled scripts."""
    src = tmp_path / "bundled_scripts"
    src.mkdir()
    (src / "mlx-big-model-close.sh").write_text("#!/bin/bash\necho close")
    (src / "mlx-big-model-restore.sh").write_text("#!/bin/bash\necho restore")
    return src


def test_install_commands_copies_files(tmp_path, monkeypatch, fake_commands_dir):
    dest = tmp_path / "commands"
    monkeypatch.setattr("mlx_mcp_server.installer._bundled_commands_dir", lambda: fake_commands_dir)

    install_commands(dest_dir=dest)

    assert (dest / "switch-model.md").exists()
    assert (dest / "big-model.md").exists()
    assert (dest / "switch-model.md").read_text() == "Switch model command"


def test_install_commands_creates_dest_dir(tmp_path, monkeypatch, fake_commands_dir):
    dest = tmp_path / "deeply" / "nested" / "commands"
    monkeypatch.setattr("mlx_mcp_server.installer._bundled_commands_dir", lambda: fake_commands_dir)

    install_commands(dest_dir=dest)

    assert dest.is_dir()
    assert (dest / "switch-model.md").exists()


def test_install_commands_dry_run(tmp_path, monkeypatch, fake_commands_dir, capsys):
    dest = tmp_path / "commands"
    monkeypatch.setattr("mlx_mcp_server.installer._bundled_commands_dir", lambda: fake_commands_dir)

    install_commands(dest_dir=dest, dry_run=True)

    assert not dest.exists(), "dry_run must not create the dest dir"
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert "switch-model" in out


def test_install_commands_missing_src(tmp_path, monkeypatch):
    nonexistent = tmp_path / "no_such_dir"
    monkeypatch.setattr("mlx_mcp_server.installer._bundled_commands_dir", lambda: nonexistent)

    with pytest.raises(RuntimeError, match="not found"):
        install_commands(dest_dir=tmp_path / "dest")


def test_install_commands_empty_src(tmp_path, monkeypatch):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.setattr("mlx_mcp_server.installer._bundled_commands_dir", lambda: empty_dir)

    with pytest.raises(RuntimeError, match="No .md files"):
        install_commands(dest_dir=tmp_path / "dest")


# ── install_scripts ───────────────────────────────────────────────────────────

def test_install_scripts_copies_files(tmp_path, monkeypatch, fake_scripts_dir):
    dest = tmp_path / "bin"
    monkeypatch.setattr("mlx_mcp_server.installer._bundled_scripts_dir", lambda: fake_scripts_dir)

    install_scripts(dest_dir=dest)

    assert (dest / "mlx-big-model-close.sh").exists()
    assert (dest / "mlx-big-model-restore.sh").exists()


def test_install_scripts_are_executable(tmp_path, monkeypatch, fake_scripts_dir):
    dest = tmp_path / "bin"
    monkeypatch.setattr("mlx_mcp_server.installer._bundled_scripts_dir", lambda: fake_scripts_dir)

    install_scripts(dest_dir=dest)

    for name in ("mlx-big-model-close.sh", "mlx-big-model-restore.sh"):
        out = dest / name
        mode = out.stat().st_mode
        assert mode & stat.S_IXUSR, f"{name} should be user-executable"


def test_install_scripts_dry_run(tmp_path, monkeypatch, fake_scripts_dir, capsys):
    dest = tmp_path / "bin"
    monkeypatch.setattr("mlx_mcp_server.installer._bundled_scripts_dir", lambda: fake_scripts_dir)

    install_scripts(dest_dir=dest, dry_run=True)

    assert not dest.exists(), "dry_run must not create the dest dir"
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert "mlx-big-model-close.sh" in out


def test_install_scripts_missing_src(tmp_path, monkeypatch):
    nonexistent = tmp_path / "no_such_dir"
    monkeypatch.setattr("mlx_mcp_server.installer._bundled_scripts_dir", lambda: nonexistent)

    with pytest.raises(RuntimeError, match="not found"):
        install_scripts(dest_dir=tmp_path / "dest")


def test_install_scripts_empty_src(tmp_path, monkeypatch):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.setattr("mlx_mcp_server.installer._bundled_scripts_dir", lambda: empty_dir)

    with pytest.raises(RuntimeError, match="No .sh files"):
        install_scripts(dest_dir=tmp_path / "dest")


# ── install() with_commands / with_scripts ────────────────────────────────────

def test_install_full_runs_all_three(tmp_path, monkeypatch, fake_commands_dir, fake_scripts_dir):
    config_file = tmp_path / "settings.json"
    commands_dest = tmp_path / "commands"
    scripts_dest = tmp_path / "bin"

    monkeypatch.setattr("mlx_mcp_server.installer._claude_code_config_path", lambda: config_file)
    monkeypatch.setattr("mlx_mcp_server.installer._bundled_commands_dir", lambda: fake_commands_dir)
    monkeypatch.setattr("mlx_mcp_server.installer._bundled_scripts_dir", lambda: fake_scripts_dir)

    install(
        claude_code=True,
        base_url="http://localhost:8080",
        model="",
        api_key="",
        dry_run=False,
        with_commands=True,
        with_scripts=True,
    )

    assert config_file.exists()
    # commands and scripts go to the default paths; since we can't easily redirect
    # those without monkeypatching Path.home(), just verify no exceptions raised.


def test_install_no_extras_skips_commands_and_scripts(tmp_path, monkeypatch):
    config_file = tmp_path / "settings.json"
    monkeypatch.setattr("mlx_mcp_server.installer._claude_code_config_path", lambda: config_file)

    # with_commands=False, with_scripts=False — should not call install_commands/scripts
    called = []

    def _noop_commands(**kwargs):
        called.append("commands")

    def _noop_scripts(**kwargs):
        called.append("scripts")

    monkeypatch.setattr("mlx_mcp_server.installer.install_commands", _noop_commands)
    monkeypatch.setattr("mlx_mcp_server.installer.install_scripts", _noop_scripts)

    install(
        claude_code=True,
        base_url="http://localhost:8080",
        model="",
        api_key="",
        dry_run=False,
        with_commands=False,
        with_scripts=False,
    )

    assert called == [], "install_commands and install_scripts should not be called when both flags are False"


def test_install_with_commands_only(tmp_path, monkeypatch):
    config_file = tmp_path / "settings.json"
    monkeypatch.setattr("mlx_mcp_server.installer._claude_code_config_path", lambda: config_file)

    called = []
    monkeypatch.setattr("mlx_mcp_server.installer.install_commands", lambda **kw: called.append("commands"))
    monkeypatch.setattr("mlx_mcp_server.installer.install_scripts", lambda **kw: called.append("scripts"))

    install(
        claude_code=True,
        base_url="http://localhost:8080",
        model="",
        api_key="",
        dry_run=False,
        with_commands=True,
        with_scripts=False,
    )

    assert called == ["commands"]


def test_install_with_scripts_only(tmp_path, monkeypatch):
    config_file = tmp_path / "settings.json"
    monkeypatch.setattr("mlx_mcp_server.installer._claude_code_config_path", lambda: config_file)

    called = []
    monkeypatch.setattr("mlx_mcp_server.installer.install_commands", lambda **kw: called.append("commands"))
    monkeypatch.setattr("mlx_mcp_server.installer.install_scripts", lambda **kw: called.append("scripts"))

    install(
        claude_code=True,
        base_url="http://localhost:8080",
        model="",
        api_key="",
        dry_run=False,
        with_commands=False,
        with_scripts=True,
    )

    assert called == ["scripts"]


# ── bundled data sanity checks ─────────────────────────────────────────────────

def test_bundled_commands_dir_exists():
    d = _bundled_commands_dir()
    assert d.is_dir(), f"Package commands dir must exist: {d}"
    md_files = list(d.glob("*.md"))
    assert len(md_files) >= 1, "At least one .md command file must be bundled"


def test_bundled_scripts_dir_exists():
    d = _bundled_scripts_dir()
    assert d.is_dir(), f"Package scripts dir must exist: {d}"
    sh_files = list(d.glob("*.sh"))
    assert len(sh_files) >= 1, "At least one .sh script file must be bundled"


def test_bundled_commands_include_expected():
    d = _bundled_commands_dir()
    names = {f.stem for f in d.glob("*.md")}
    assert "switch-model" in names
    assert "big-model" in names
    assert "big-model-done" in names


def test_bundled_scripts_include_expected():
    d = _bundled_scripts_dir()
    names = {f.name for f in d.glob("*.sh")}
    assert "mlx-big-model-close.sh" in names
    assert "mlx-big-model-restore.sh" in names
