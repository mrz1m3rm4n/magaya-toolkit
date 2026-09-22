"""Tests for how the `.env` file is located. No network access.

Pydantic resolves a relative `env_file` against the working directory, which is
why the CLI used to only work from the one directory holding the file. These
tests pin the replacement: nearest first, walking up, with a user-level file as
the last resort — and an explicit `MAGAYA_ENV_FILE` that stops the search dead
so a typo fails loudly instead of quietly loading someone else's credentials.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from magaya_toolkit.infrastructure.config import (
    MagayaSettings,
    candidate_env_files,
    find_env_file,
    user_config_dir,
)

_ENV_BODY = (
    "MAGAYA_API_URL=https://example.test/api\n"
    "MAGAYA_USERNAME=someone\n"
    "MAGAYA_PASSWORD=secret\n"
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Start from an environment that cannot leak the developer's own settings."""
    for name in (
        "MAGAYA_ENV_FILE",
        "MAGAYA_API_URL",
        "MAGAYA_USERNAME",
        "MAGAYA_PASSWORD",
        "XDG_CONFIG_HOME",
    ):
        monkeypatch.delenv(name, raising=False)


def _write_env(directory: Path, url: str = "https://example.test/api") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ".env"
    path.write_text(_ENV_BODY.replace("https://example.test/api", url))
    return path


# -- walking up ------------------------------------------------------------


def test_finds_the_env_file_in_the_current_directory(tmp_path, monkeypatch):
    expected = _write_env(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert find_env_file() == expected


def test_finds_it_from_a_nested_subdirectory(tmp_path, monkeypatch):
    """This is the bug: a CLI is normally run from somewhere inside a project."""
    expected = _write_env(tmp_path)
    nested = tmp_path / "src" / "package" / "domain"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    assert find_env_file() == expected


def test_the_nearest_env_file_wins_over_a_further_parent(tmp_path, monkeypatch):
    _write_env(tmp_path, url="https://far.test/api")
    nearer = _write_env(tmp_path / "project", url="https://near.test/api")
    monkeypatch.chdir(tmp_path / "project")

    assert find_env_file() == nearer
    assert MagayaSettings().api_url == "https://near.test/api"


def test_no_env_file_anywhere_yields_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty-config"))

    assert find_env_file() is None


# -- the user-level fallback ----------------------------------------------


def test_falls_back_to_the_user_config_directory(tmp_path, monkeypatch):
    config_home = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    expected = _write_env(config_home / "magaya-toolkit", url="https://user.test/api")
    # Somewhere with no .env of its own, and no project above it.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert find_env_file() == expected
    assert MagayaSettings().api_url == "https://user.test/api"


def test_the_user_config_directory_honours_xdg_config_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    assert user_config_dir() == tmp_path / "xdg" / "magaya-toolkit"


def test_without_xdg_it_defaults_under_dot_config(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    assert user_config_dir() == tmp_path / ".config" / "magaya-toolkit"


# -- the explicit override -------------------------------------------------


def test_an_explicit_env_file_wins_over_a_nearer_one(tmp_path, monkeypatch):
    _write_env(tmp_path, url="https://nearby.test/api")
    chosen = _write_env(tmp_path / "chosen", url="https://chosen.test/api")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAGAYA_ENV_FILE", str(chosen))

    assert find_env_file() == chosen
    assert MagayaSettings().api_url == "https://chosen.test/api"


def test_a_bad_explicit_path_does_not_silently_fall_back(tmp_path, monkeypatch):
    """A typo must fail, not quietly load whatever .env happens to be nearby."""
    _write_env(tmp_path, url="https://nearby.test/api")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAGAYA_ENV_FILE", str(tmp_path / "does-not-exist"))

    assert find_env_file() is None
    assert list(candidate_env_files()) == [tmp_path / "does-not-exist"]


# -- precedence ------------------------------------------------------------


def test_real_environment_variables_win_over_the_file(tmp_path, monkeypatch):
    _write_env(tmp_path, url="https://from-file.test/api")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAGAYA_API_URL", "https://from-env.test/api")

    settings = MagayaSettings()

    assert settings.api_url == "https://from-env.test/api"
    # The file still supplies what the environment does not.
    assert settings.username == "someone"


def test_explicit_arguments_win_over_everything(tmp_path, monkeypatch):
    _write_env(tmp_path)
    monkeypatch.chdir(tmp_path)

    settings = MagayaSettings(
        api_url="https://explicit.test/api", username="u", password="p"
    )

    assert settings.api_url == "https://explicit.test/api"
