from dataclasses import replace
from pathlib import Path

import pytest

from naga_control.adapters.config import (
    ConfigDurabilityError,
    ConfigPathError,
    ConfigWriteError,
    TomlConfigStore,
    default_config_path,
    storage,
)
from naga_control.domain import default_configuration


def test_default_config_path_uses_xdg_home_or_home_fallback(tmp_path: Path) -> None:
    home = tmp_path / "home"

    assert default_config_path({}, home) == home / ".config" / "naga-control" / "config.toml"
    assert default_config_path({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}, home) == (
        tmp_path / "xdg" / "naga-control" / "config.toml"
    )


def test_default_config_path_rejects_relative_xdg_home(tmp_path: Path) -> None:
    with pytest.raises(ConfigPathError) as error:
        default_config_path({"XDG_CONFIG_HOME": "relative/config"}, tmp_path)

    assert error.value.field_path == "XDG_CONFIG_HOME"


def test_load_returns_none_for_a_missing_target(tmp_path: Path) -> None:
    store = TomlConfigStore(tmp_path / "naga-control" / "config.toml")

    assert store.load() is None
    assert not store.path.parent.exists()


def test_save_and_load_round_trip_with_private_target_mode(tmp_path: Path) -> None:
    path = tmp_path / "naga-control" / "config.toml"
    configuration = default_configuration()

    TomlConfigStore(path).save(configuration)

    assert TomlConfigStore(path).load() == configuration
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert path.stat().st_mode & 0o777 == 0o600


def test_save_hardens_an_existing_config_directory(tmp_path: Path) -> None:
    parent = tmp_path / "naga-control"
    parent.mkdir(mode=0o755)

    TomlConfigStore(parent / "config.toml").save(default_configuration())

    assert parent.stat().st_mode & 0o777 == 0o700


def test_save_replaces_atomically_without_leaving_a_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "naga-control" / "config.toml"
    store = TomlConfigStore(path)
    original_replace = storage.os.replace
    replacements: list[tuple[Path, Path]] = []

    def record_replace(source: Path, destination: Path) -> None:
        replacements.append((source, destination))
        original_replace(source, destination)

    monkeypatch.setattr(storage.os, "replace", record_replace)

    store.save(default_configuration())

    assert replacements[0][1] == path
    assert replacements[0][0].parent == path.parent
    assert not replacements[0][0].exists()
    assert not list(path.parent.glob(f".{path.name}.*.tmp"))


def test_pre_replace_failure_preserves_existing_configuration_and_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "naga-control" / "config.toml"
    store = TomlConfigStore(path)
    original = default_configuration()
    store.save(original)

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(storage.os, "replace", fail_replace)

    with pytest.raises(ConfigWriteError, match="simulated replace failure"):
        store.save(replace(original, revision=1))

    assert store.load() == original
    assert not list(path.parent.glob(f".{path.name}.*.tmp"))


def test_post_replace_fsync_failure_reports_uncertain_durability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "naga-control" / "config.toml"
    store = TomlConfigStore(path)
    original = default_configuration()
    store.save(original)
    updated = replace(original, revision=1)

    def fail_directory_fsync(_path: Path) -> None:
        raise OSError("simulated directory fsync failure")

    monkeypatch.setattr(storage, "_fsync_directory", fail_directory_fsync)

    with pytest.raises(ConfigDurabilityError, match="simulated directory fsync failure"):
        store.save(updated)

    assert store.load() == updated
