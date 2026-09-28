"""Atomic filesystem storage for the versioned TOML configuration."""

import os
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path

from naga_control.config import dump_toml, parse_toml
from naga_control.domain.profiles import Configuration


class ConfigPathError(ValueError):
    """A configuration path setting is invalid."""

    def __init__(self, field_path: str, message: str) -> None:
        self.field_path = field_path
        self.message = message
        super().__init__(f"{field_path}: {message}")


class ConfigReadError(OSError):
    """Configuration storage could not be read."""

    def __init__(self, path: Path, cause: OSError) -> None:
        self.path = path
        super().__init__(f"could not read configuration at {path}: {cause}")


class ConfigWriteError(OSError):
    """Configuration storage could not be written durably."""

    def __init__(self, path: Path, cause: OSError) -> None:
        self.path = path
        super().__init__(f"could not write configuration at {path}: {cause}")


class ConfigDurabilityError(ConfigWriteError):
    """Configuration replacement succeeded but its durable commit is unknown."""

    def __init__(self, path: Path, cause: OSError) -> None:
        super().__init__(path, cause)


def default_config_path(environ: Mapping[str, str], home: Path) -> Path:
    """Return the XDG configuration path without consulting process environment."""
    config_home = environ.get("XDG_CONFIG_HOME")
    if not config_home:
        return home / ".config" / "naga-control" / "config.toml"
    base_path = Path(config_home)
    if not base_path.is_absolute():
        raise ConfigPathError("XDG_CONFIG_HOME", "must be an absolute path")
    return base_path / "naga-control" / "config.toml"


class TomlConfigStore:
    """Load and atomically replace one TOML configuration file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> Configuration | None:
        """Load the target, returning ``None`` only when it does not exist."""
        try:
            document = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise ConfigReadError(self.path, exc) from exc
        return parse_toml(document)

    def save(self, configuration: Configuration) -> None:
        """Validate, serialize, and durably atomically replace the target."""
        document = dump_toml(configuration)
        parse_toml(document)

        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self.path.parent, 0o700)
        except OSError as exc:
            raise ConfigWriteError(self.path, exc) from exc

        temporary_path: Path | None = None
        replaced = False
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "w", encoding="utf-8") as temporary_file:
                os.fchmod(temporary_file.fileno(), 0o600)
                temporary_file.write(document)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, self.path)
            replaced = True
        except OSError as exc:
            if temporary_path is not None and not replaced:
                _remove_temporary_file(temporary_path)
            raise ConfigWriteError(self.path, exc) from exc
        try:
            _fsync_directory(self.path.parent)
        except OSError as exc:
            raise ConfigDurabilityError(self.path, exc) from exc


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _remove_temporary_file(path: Path) -> None:
    with suppress(OSError):
        path.unlink(missing_ok=True)
