import os
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class Config:
    base_url: str
    default_model: str
    api_key: str
    timeout: int

def load_config(env: Optional[dict] = None) -> Config:
    if env is None:
        env = os.environ

    raw_timeout = env.get("MLX_TIMEOUT", "30")
    try:
        timeout = int(raw_timeout)
        if timeout <= 0:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError(f"MLX_TIMEOUT must be a positive integer, got: {raw_timeout!r}")

    return Config(
        base_url=env.get("MLX_BASE_URL", "http://localhost:8080").rstrip("/"),
        default_model=env.get("MLX_DEFAULT_MODEL", ""),
        api_key=env.get("MLX_API_KEY", ""),
        timeout=timeout,
    )
