"""Server configuration loaded from environment variables."""
import os
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

@dataclass(frozen=True)
class Config:
    """Server configuration: base_url, api_key, timeout, and default_model."""
    base_url: str
    default_model: str
    api_key: str
    timeout: int

def load_config(env: Optional[dict] = None) -> Config:
    """Build a Config from environment variables."""
    if env is None:
        env = os.environ

    raw_timeout = env.get("MLX_TIMEOUT", "30")
    try:
        timeout = int(raw_timeout)
        if timeout <= 0:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError(f"MLX_TIMEOUT must be a positive integer, got: {raw_timeout!r}")

    raw_url = env.get("MLX_BASE_URL", "http://localhost:8080").rstrip("/")
    parsed = urlparse(raw_url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"MLX_BASE_URL must use http:// or https://, got: {raw_url!r}"
        )

    # Strip any embedded credentials from the URL before storing
    safe_netloc = parsed.hostname or ""
    if parsed.port:
        safe_netloc += f":{parsed.port}"
    safe_url = parsed._replace(netloc=safe_netloc).geturl()

    return Config(
        base_url=safe_url,
        default_model=env.get("MLX_DEFAULT_MODEL", ""),
        api_key=env.get("MLX_API_KEY", ""),
        timeout=timeout,
    )
