import tomllib
from pathlib import Path


def test_console_script_registered():
    data = tomllib.loads(Path("pyproject.toml").read_text())
    assert data["project"]["scripts"]["mlx-offload-hook"] == "mlx_mcp_server.hook.__main__:main"
