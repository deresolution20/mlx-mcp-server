# tests/test_installer.py
import json
import os
import pytest
from pathlib import Path
from mlx_mcp_server.installer import install, _claude_desktop_config_path, _claude_code_config_path


def test_claude_code_config_path():
    path = _claude_code_config_path()
    assert path == Path.home() / ".claude" / "settings.json"


def test_install_creates_config_file(tmp_path, monkeypatch):
    config_file = tmp_path / "claude_desktop_config.json"
    monkeypatch.setattr("mlx_mcp_server.installer._claude_desktop_config_path", lambda: config_file)

    install(claude_code=False, base_url="http://localhost:8080", model="", dry_run=False)

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

    install(claude_code=False, base_url="http://localhost:8080", model="", dry_run=False)

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

    install(claude_code=False, base_url="http://localhost:8080", model="mistral", dry_run=False)

    data = json.loads(config_file.read_text())
    assert data["mcpServers"]["mlx"]["env"]["MLX_BASE_URL"] == "http://localhost:8080"
    assert data["mcpServers"]["mlx"]["env"]["MLX_DEFAULT_MODEL"] == "mistral"


def test_install_dry_run_does_not_write(tmp_path, monkeypatch, capsys):
    config_file = tmp_path / "claude_desktop_config.json"
    monkeypatch.setattr("mlx_mcp_server.installer._claude_desktop_config_path", lambda: config_file)

    install(claude_code=False, base_url="http://localhost:8080", model="", dry_run=True)

    assert not config_file.exists()
    captured = capsys.readouterr()
    assert "mlx-mcp-server" in captured.out


def test_install_claude_code(tmp_path, monkeypatch):
    config_file = tmp_path / "settings.json"
    monkeypatch.setattr("mlx_mcp_server.installer._claude_code_config_path", lambda: config_file)

    install(claude_code=True, base_url="http://localhost:8080", model="", dry_run=False)

    data = json.loads(config_file.read_text())
    assert "mlx" in data["mcpServers"]
