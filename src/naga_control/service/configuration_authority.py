"""Authoritative loaded configuration and its durable updates."""

from collections.abc import Callable
from dataclasses import replace

from naga_control.config import dump_toml, parse_toml
from naga_control.domain.defaults import default_configuration
from naga_control.domain.profiles import Configuration
from naga_control.ports.config_store import ConfigurationStore


class StaleConfigurationRevisionError(RuntimeError):
    """The requested revision is no longer current."""


class UnknownProfileError(ValueError):
    """The requested profile does not exist."""


class ConfigurationAuthority:
    """Synchronous configuration operations, serialized by the service's lock."""

    def __init__(
        self,
        load_configuration: Callable[[], Configuration | None],
        store: ConfigurationStore | None = None,
    ) -> None:
        self._load_configuration = load_configuration
        self._store = store
        self._current: Configuration | None = None

    @property
    def current(self) -> Configuration | None:
        return self._current

    def load(self) -> None:
        self._current = self._load_configuration() or default_configuration()

    def require_current(self) -> Configuration:
        if self._current is None:
            raise RuntimeError("Naga service has no loaded configuration")
        return self._current

    def save(self, configuration: Configuration) -> None:
        if self._store is not None:
            self._store.save(configuration)
        self._current = configuration

    def document(self) -> str:
        return dump_toml(self.require_current())

    def revision(self) -> int:
        return self.require_current().revision

    @staticmethod
    def parse(document: str) -> Configuration:
        return parse_toml(document)

    def validate_revision(self, expected_revision: int, configuration: Configuration) -> None:
        current = self.require_current()
        if expected_revision != current.revision or configuration.revision != current.revision + 1:
            raise StaleConfigurationRevisionError(
                f"expected base revision {current.revision}, got {expected_revision}"
            )

    def apply(self, expected_revision: int, configuration: Configuration) -> int:
        self.validate_revision(expected_revision, configuration)
        self.save(configuration)
        return configuration.revision

    def select_profile(self, profile_id: str) -> int:
        current = self.require_current()
        if profile_id not in {identifier for identifier, _ in current.profiles}:
            raise UnknownProfileError(f"unknown profile {profile_id!r}")
        updated = replace(current, active_profile=profile_id, revision=current.revision + 1)
        self.save(updated)
        return updated.revision
