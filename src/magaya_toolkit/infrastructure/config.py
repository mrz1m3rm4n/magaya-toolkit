"""Runtime settings for the Magaya API adapter.

Loaded from environment variables (prefixed `MAGAYA_`) and a `.env` file.

Finding that file is the fiddly part. Pydantic resolves a relative `env_file`
against the current working directory, which means a CLI only works from the
one directory the file happens to sit in. Instead, `.env` is looked for the way
`git` looks for a repository: nearest first, walking up from where you are,
with a user-level file as the last resort.

Search order, first hit wins:

1. `MAGAYA_ENV_FILE`, if set — the explicit escape hatch.
2. `.env` in the current directory, then each parent up to the filesystem root.
3. `.env` under the user config directory (`$XDG_CONFIG_HOME/magaya-toolkit`,
   or `~/.config/magaya-toolkit`).

Real environment variables always win over whatever the file says, so
`MAGAYA_API_URL=… magaya shipments …` overrides a `.env` without editing it.

Kept in `infrastructure/` because it depends on `pydantic-settings`, a framework
concern; the domain and application layers never import it.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE_NAME = ".env"
_ENV_FILE_OVERRIDE = "MAGAYA_ENV_FILE"
_APP_DIR_NAME = "magaya-toolkit"


def user_config_dir() -> Path:
    """The per-user config directory, honouring `$XDG_CONFIG_HOME`."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / _APP_DIR_NAME


def candidate_env_files() -> Iterator[Path]:
    """Yield the `.env` locations that are searched, in order of precedence."""
    override = os.environ.get(_ENV_FILE_OVERRIDE)
    if override:
        # An explicit path is a deliberate choice: use it and look no further,
        # so a typo fails loudly instead of silently loading someone else's.
        yield Path(override).expanduser()
        return

    try:
        here = Path.cwd().resolve()
    except OSError:  # pragma: no cover - the cwd was deleted underneath us
        here = None
    if here is not None:
        for directory in (here, *here.parents):
            yield directory / _ENV_FILE_NAME

    yield user_config_dir() / _ENV_FILE_NAME


def find_env_file() -> Path | None:
    """Return the first `.env` that exists, or None when there is none."""
    for candidate in candidate_env_files():
        if candidate.is_file():
            return candidate
    return None


class MagayaSettings(BaseSettings):
    """Connection settings for the Magaya SOAP endpoint.

    The `env_prefix` maps `api_url` -> `MAGAYA_API_URL`, `username` ->
    `MAGAYA_USERNAME`, `password` -> `MAGAYA_PASSWORD`.

    The `.env` file is located by `find_env_file()` — see the module docstring
    — so the CLI works from any directory inside your project, not just the one
    holding the file.
    """

    api_url: str
    username: str
    password: str

    model_config = SettingsConfigDict(
        env_prefix="MAGAYA_",
        extra="ignore",
    )

    def __init__(self, **values: Any) -> None:
        # Resolve the file at construction time, not import time: the working
        # directory can differ between importing the package and using it.
        values.setdefault("_env_file", find_env_file())
        super().__init__(**values)
