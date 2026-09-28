from pathlib import Path

from naga_control.adapters.evdev.discovery import NagaConnection
from naga_control.application.service_factory import create_service
from naga_control.domain.defaults import default_configuration
from naga_control.domain.profiles import Configuration


def test_factory_defers_discovery_and_configuration_loading_until_service_start() -> None:
    calls: list[str] = []
    configuration = default_configuration()

    service = create_service(
        environ={"XDG_CONFIG_HOME": "/tmp/config"},
        home=Path("/unused"),
        discover=lambda: _discover(calls),
        load_configuration=lambda: _load(calls, configuration),
    )

    assert calls == []
    assert service is not None


def _discover(calls: list[str]) -> tuple[NagaConnection, ...]:
    calls.append("discover")
    return ()


def _load(calls: list[str], configuration: Configuration) -> Configuration:
    calls.append("load")
    return configuration
