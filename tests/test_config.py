# tests/test_config.py
import os
import pytest
from mlx_mcp_server.config import Config, load_config

def test_load_config_defaults():
    env = {}
    config = load_config(env)
    assert config.base_url == "http://localhost:8080"
    assert config.default_model == ""
    assert config.api_key == ""
    assert config.timeout == 30

def test_load_config_from_env():
    env = {
        "MLX_BASE_URL": "http://localhost:11434",
        "MLX_DEFAULT_MODEL": "mistral",
        "MLX_API_KEY": "secret",
        "MLX_TIMEOUT": "60",
    }
    config = load_config(env)
    assert config.base_url == "http://localhost:11434"
    assert config.default_model == "mistral"
    assert config.api_key == "secret"
    assert config.timeout == 60

def test_load_config_invalid_timeout_raises():
    with pytest.raises(ValueError, match="MLX_TIMEOUT must be a positive integer"):
        load_config({"MLX_TIMEOUT": "not-a-number"})

def test_load_config_uses_os_environ_by_default(monkeypatch):
    monkeypatch.setenv("MLX_BASE_URL", "http://custom:9999")
    config = load_config()
    assert config.base_url == "http://custom:9999"
