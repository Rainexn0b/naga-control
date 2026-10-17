"""Fakes for autostart and service-restart panel tests (tmp only, no host I/O)."""

import asyncio
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from naga_control.gui.autostart import AutostartStore
from naga_control.gui.service_restart import RestartResult


def sync_run(factory: Callable[[], Coroutine[Any, Any, object]]) -> None:
    asyncio.run(factory())


def tmp_autostart_path(tmp_path: Path) -> Path:
    return tmp_path / "config" / "autostart" / "org.nagacontrol.NagaControl.desktop"


def fake_launcher(
    argv: list[str] | None, error: str | None = None
) -> Callable[[], tuple[list[str] | None, str | None]]:
    def probe() -> tuple[list[str] | None, str | None]:
        return (list(argv) if argv is not None else None, error)

    return probe


def make_store(tmp_path: Path, argv: list[str] | None, error: str | None = None) -> AutostartStore:
    return AutostartStore(tmp_autostart_path(tmp_path), launcher=fake_launcher(argv, error))


class FakeRestarter:
    """Record restart calls without touching systemctl."""

    def __init__(self, result: RestartResult | None = None) -> None:
        self.calls = 0
        self.result = result if result is not None else RestartResult(ok=True)

    async def __call__(self) -> RestartResult:
        self.calls += 1
        return self.result
