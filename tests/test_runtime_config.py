# tests/test_runtime_config.py
"""Unit tests for runtime_config read/write helpers."""

import pytest
from pathlib import Path
from unittest.mock import patch


def _make_module(tmp_path: Path):
    """Return a fresh runtime_config module backed by a temp directory."""
    import importlib, sys
    # Patch the config dir before importing so the module uses our temp dir
    model_file = tmp_path / "active_model"
    with patch("mlx_mcp_server.runtime_config._CONFIG_DIR", tmp_path), \
         patch("mlx_mcp_server.runtime_config._MODEL_FILE", model_file):
        from mlx_mcp_server import runtime_config
        importlib.reload(runtime_config)
        yield runtime_config, model_file
    importlib.reload(runtime_config)  # restore


def test_read_returns_empty_when_no_file(tmp_path):
    model_file = tmp_path / "active_model"
    with patch("mlx_mcp_server.runtime_config._MODEL_FILE", model_file):
        from mlx_mcp_server.runtime_config import read_runtime_model
        assert read_runtime_model() == ""


def test_write_and_read_roundtrip(tmp_path):
    model_file = tmp_path / "active_model"
    with patch("mlx_mcp_server.runtime_config._CONFIG_DIR", tmp_path), \
         patch("mlx_mcp_server.runtime_config._MODEL_FILE", model_file):
        from mlx_mcp_server.runtime_config import read_runtime_model, write_runtime_model
        write_runtime_model("Qwen2.5-Coder-32B-Instruct-4bit")
        assert read_runtime_model() == "Qwen2.5-Coder-32B-Instruct-4bit"


def test_write_empty_removes_file(tmp_path):
    model_file = tmp_path / "active_model"
    with patch("mlx_mcp_server.runtime_config._CONFIG_DIR", tmp_path), \
         patch("mlx_mcp_server.runtime_config._MODEL_FILE", model_file):
        from mlx_mcp_server.runtime_config import read_runtime_model, write_runtime_model
        write_runtime_model("some-model")
        assert model_file.exists()
        write_runtime_model("")
        assert not model_file.exists()
        assert read_runtime_model() == ""


def test_write_empty_is_idempotent_when_no_file(tmp_path):
    model_file = tmp_path / "active_model"
    with patch("mlx_mcp_server.runtime_config._CONFIG_DIR", tmp_path), \
         patch("mlx_mcp_server.runtime_config._MODEL_FILE", model_file):
        from mlx_mcp_server.runtime_config import write_runtime_model
        # Should not raise even if file doesn't exist
        write_runtime_model("")
        write_runtime_model("")
