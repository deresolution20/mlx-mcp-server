import json
import stat
import pytest
from pathlib import Path

from mlx_mcp_server.installer import install_offload_layer, _bundled_offload_dir


@pytest.fixture
def fake_offload_dir(tmp_path):
    root = tmp_path / "offload"
    (root / "hooks").mkdir(parents=True)
    (root / "skills" / "offload").mkdir(parents=True)
    (root / "hooks" / "offload-reminder.sh").write_text("#!/usr/bin/env bash\necho remind")
    (root / "hooks" / "offload-subagent-nudge.sh").write_text("#!/usr/bin/env bash\necho nudge")
    (root / "skills" / "offload" / "SKILL.md").write_text("# offload skill")
    return root


def _setup(monkeypatch, fake_offload_dir, tmp_path):
    settings = tmp_path / "settings.json"
    hooks_dest = tmp_path / "hooks"
    skills_dest = tmp_path / "skills"
    monkeypatch.setattr("mlx_mcp_server.installer._bundled_offload_dir", lambda: fake_offload_dir)
    return settings, hooks_dest, skills_dest


def test_offload_installs_scripts_and_skill(monkeypatch, fake_offload_dir, tmp_path):
    settings, hooks_dest, skills_dest = _setup(monkeypatch, fake_offload_dir, tmp_path)
    install_offload_layer(
        settings_path=settings, hooks_dir=hooks_dest, skills_dir=skills_dest,
    )
    assert (hooks_dest / "offload-reminder.sh").exists()
    assert (skills_dest / "offload" / "SKILL.md").exists()
    # hook script is executable
    mode = (hooks_dest / "offload-reminder.sh").stat().st_mode
    assert mode & stat.S_IXUSR


def test_offload_registers_hooks_in_settings(monkeypatch, fake_offload_dir, tmp_path):
    settings, hooks_dest, skills_dest = _setup(monkeypatch, fake_offload_dir, tmp_path)
    install_offload_layer(settings_path=settings, hooks_dir=hooks_dest, skills_dir=skills_dest)
    data = json.loads(settings.read_text())
    assert "UserPromptSubmit" in data["hooks"]
    pretool = data["hooks"]["PreToolUse"]
    assert any(entry.get("matcher") == "Task" for entry in pretool)


def test_offload_preserves_existing_settings(monkeypatch, fake_offload_dir, tmp_path):
    settings, hooks_dest, skills_dest = _setup(monkeypatch, fake_offload_dir, tmp_path)
    settings.write_text(json.dumps({"mcpServers": {"mlx": {"command": "x"}}}))
    install_offload_layer(settings_path=settings, hooks_dir=hooks_dest, skills_dir=skills_dest)
    data = json.loads(settings.read_text())
    assert "mlx" in data["mcpServers"]
    assert "UserPromptSubmit" in data["hooks"]


def test_offload_is_idempotent(monkeypatch, fake_offload_dir, tmp_path):
    settings, hooks_dest, skills_dest = _setup(monkeypatch, fake_offload_dir, tmp_path)
    install_offload_layer(settings_path=settings, hooks_dir=hooks_dest, skills_dir=skills_dest)
    install_offload_layer(settings_path=settings, hooks_dir=hooks_dest, skills_dir=skills_dest)
    data = json.loads(settings.read_text())
    # exactly one UserPromptSubmit group and one Task matcher after running twice
    assert len(data["hooks"]["UserPromptSubmit"]) == 1
    assert sum(1 for e in data["hooks"]["PreToolUse"] if e.get("matcher") == "Task") == 1


def test_offload_dry_run_writes_nothing(monkeypatch, fake_offload_dir, tmp_path, capsys):
    settings, hooks_dest, skills_dest = _setup(monkeypatch, fake_offload_dir, tmp_path)
    install_offload_layer(
        settings_path=settings, hooks_dir=hooks_dest, skills_dir=skills_dest, dry_run=True,
    )
    assert not settings.exists()
    assert not hooks_dest.exists()
    assert "dry-run" in capsys.readouterr().out


def test_bundled_offload_dir_exists():
    d = _bundled_offload_dir()
    assert (d / "hooks" / "offload-reminder.sh").exists()
    assert (d / "skills" / "offload" / "SKILL.md").exists()


from mlx_mcp_server.installer import install


def test_install_with_offload_calls_layer(tmp_path, monkeypatch):
    config_file = tmp_path / "settings.json"
    monkeypatch.setattr("mlx_mcp_server.installer._claude_code_config_path", lambda: config_file)
    called = []
    monkeypatch.setattr(
        "mlx_mcp_server.installer.install_offload_layer",
        lambda **kw: called.append(kw),
    )
    install(
        claude_code=True, base_url="http://localhost:8080", model="", api_key="",
        dry_run=False, with_offload=True,
    )
    assert len(called) == 1


def test_install_without_offload_skips_layer(tmp_path, monkeypatch):
    config_file = tmp_path / "settings.json"
    monkeypatch.setattr("mlx_mcp_server.installer._claude_code_config_path", lambda: config_file)
    called = []
    monkeypatch.setattr(
        "mlx_mcp_server.installer.install_offload_layer",
        lambda **kw: called.append(kw),
    )
    install(
        claude_code=True, base_url="http://localhost:8080", model="", api_key="",
        dry_run=False, with_offload=False,
    )
    assert called == []
