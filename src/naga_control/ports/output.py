"""Ports for virtual keyboard and mouse output devices."""

from typing import Protocol

from naga_control.domain.intents import KeyOutputIntent, MouseButtonOutputIntent


class KeyboardOutput(Protocol):
    def emit(self, intent: KeyOutputIntent) -> None: ...

    def release_all(self) -> None: ...

    def close(self) -> None: ...


class MouseOutput(Protocol):
    def emit(self, intent: MouseButtonOutputIntent) -> None: ...

    def release_all(self) -> None: ...

    def close(self) -> None: ...
