"""CLI composition/exit tests: no hardware factories, bus, discovery, or signals."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable, Coroutine
from types import CoroutineType

import pytest
from test_service_cli import Service

from naga_control.service import service_cli


class MainBoundary:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.service = Service()
        self.lifecycle = object()
        self.events: list[str] = []
        self.levels: list[int] = []
        self.errors: dict[str, BaseException] = {}
        self.coroutines_closed = 0

        def record(phase: str) -> None:
            self.events.append(phase)
            if phase in self.errors:
                raise self.errors[phase]

        def create_service() -> Service:
            record("service")
            return self.service

        def create_lifecycle(provider: object, service: object) -> object:
            assert service is self.service
            record("lifecycle")
            return self.lifecycle

        async def watcher() -> None:
            pytest.fail("patched asyncio.run must not execute the watcher")

        def create_watcher(
            service: object, discover: object
        ) -> Callable[[], Coroutine[None, None, None]]:
            assert service is self.service
            assert discover is forbidden
            record("watcher")
            return watcher

        def forbidden(*args: object, **kwargs: object) -> None:
            pytest.fail("real discovery, bus, or signal registration must never run")

        def fake_asyncio_run(coroutine: CoroutineType[None, None, None]) -> None:
            try:
                assert coroutine.cr_code is service_cli.run.__code__
                record("runner")
            finally:
                coroutine.close()
                self.coroutines_closed += 1

        def configure_logging(*, level: int) -> None:
            self.levels.append(level)

        monkeypatch.setattr(service_cli, "create_service", create_service)
        monkeypatch.setattr(service_cli, "OpenRazerLifecycleMonitor", create_lifecycle)
        monkeypatch.setattr(service_cli, "create_udev_topology_watcher", create_watcher)
        monkeypatch.setattr(service_cli, "discover_naga_connections", forbidden)
        monkeypatch.setattr(service_cli, "connect_session_bus", forbidden)
        monkeypatch.setattr(service_cli.asyncio, "run", fake_asyncio_run)
        monkeypatch.setattr(service_cli.logging, "basicConfig", configure_logging)
        monkeypatch.setattr(service_cli.signal, "signal", forbidden)


@pytest.fixture
def boundary(monkeypatch: pytest.MonkeyPatch) -> MainBoundary:
    return MainBoundary(monkeypatch)


@pytest.mark.parametrize("debug", [False, True])
def test_main_normal_and_debug_exit_zero_without_starting_real_service(
    boundary: MainBoundary, monkeypatch: pytest.MonkeyPatch, debug: bool
) -> None:
    monkeypatch.setattr(sys, "argv", ["naga-control-service"] + (["--debug"] if debug else []))
    assert service_cli.main() == 0
    assert boundary.events == ["service", "lifecycle", "watcher", "runner"]
    assert boundary.levels == [logging.DEBUG if debug else logging.INFO]
    assert boundary.coroutines_closed == 1
    assert boundary.service.events == []


@pytest.mark.parametrize("phase", ["service", "lifecycle", "watcher", "runner"])
@pytest.mark.parametrize("error_type", [RuntimeError, KeyboardInterrupt])
def test_main_startup_errors_and_interruptions_have_observable_exit_codes(
    boundary: MainBoundary,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    phase: str,
    error_type: type[BaseException],
) -> None:
    monkeypatch.setattr(sys, "argv", ["naga-control-service"])
    original = error_type("fake startup failure")
    boundary.errors[phase] = original
    try:
        result = service_cli.main()
    except BaseException as exc:
        pytest.fail(f"main leaked {type(exc).__name__} instead of returning an exit code")
    assert result == (130 if error_type is KeyboardInterrupt else 1)
    phases = ["service", "lifecycle", "watcher", "runner"]
    assert boundary.events == phases[: phases.index(phase) + 1]
    assert boundary.coroutines_closed == int(phase == "runner")
    assert boundary.service.events == []
    records = [record for record in caplog.records if record.name == service_cli.__name__]
    if error_type is KeyboardInterrupt:
        assert records == []
    else:
        assert len(records) == 1
        assert records[0].levelno == logging.ERROR
        assert "service stopped during startup" in records[0].getMessage()
        assert records[0].exc_info is not None
        assert records[0].exc_info[1] is original


@pytest.mark.parametrize("argument, code", [("--help", 0), ("--unknown-option", 2)])
def test_main_parser_exits_before_composition_or_logging(
    boundary: MainBoundary,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argument: str,
    code: int,
) -> None:
    monkeypatch.setattr(sys, "argv", ["naga-control-service", argument])
    with pytest.raises(SystemExit) as raised:
        service_cli.main()
    assert raised.value.code == code
    output = capsys.readouterr()
    if code == 0:
        assert "usage: naga-control-service" in output.out
        assert "--debug" in output.out
        assert output.err == ""
    else:
        assert "unrecognized arguments: --unknown-option" in output.err
        assert output.out == ""
    assert boundary.events == boundary.levels == []
    assert boundary.coroutines_closed == 0
