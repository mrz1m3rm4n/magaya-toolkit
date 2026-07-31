"""Runtime settings for the Magaya API adapter.

Loaded from environment variables (prefixed `MAGAYA_`) and an optional `.env`
file. Kept in `infrastructure/` because it depends on `pydantic-settings`, a
framework concern; the domain and application layers never import it.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class MagayaSettings(BaseSettings):
    """Connection settings for the Magaya SOAP endpoint.

    The `env_prefix` maps `api_url` -> `MAGAYA_API_URL`, `username` ->
    `MAGAYA_USERNAME`, `password` -> `MAGAYA_PASSWORD`.
    """

    api_url: str
    username: str
    password: str

    model_config = SettingsConfigDict(
        env_prefix="MAGAYA_",
        env_file=".env",
        extra="ignore",
    )
