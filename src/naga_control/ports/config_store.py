"""Port for the single durable configuration document."""

from typing import Protocol

from naga_control.domain.profiles import Configuration


class ConfigurationStore(Protocol):
    """The service is the sole writer through this port."""

    def load(self) -> Configuration | None: ...

    def save(self, configuration: Configuration) -> None: ...
