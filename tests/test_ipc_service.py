import asyncio
import json

import pytest
from dbus_next.errors import DBusError

from naga_control.config import dump_toml, parse_toml
from naga_control.domain.defaults import default_configuration
from naga_control.ipc.service import BUS_NAME, INTERFACE_NAME, OBJECT_PATH, NagaControlInterface
from naga_control.service.runtime import StaleConfigurationRevisionError, UnknownProfileError


class Service:
    def __init__(self) -> None:
        self.released = False
        self._calibrating = False

    def snapshot(self) -> dict[str, object]:
        return {
            "status": "available",
            "generation": 3,
            "transport": "hyperspeed",
            "error": None,
            "calibrating": self._calibrating,
        }

    def release_all(self) -> None:
        self.released = True

    def configuration_document(self) -> str:
        return dump_toml(default_configuration())

    def configuration_revision(self) -> int:
        return 0

    async def apply_configuration(self, expected_revision: int, document: str) -> int:
        raise StaleConfigurationRevisionError("stale")

    async def select_profile(self, profile_id: str) -> int:
        raise UnknownProfileError("nope")

    async def begin_calibration(self) -> bool:
        self._calibrating = True
        return True

    async def end_calibration(self) -> bool:
        self._calibrating = False
        return False


def test_calibration_methods_toggle_the_snapshot_flag() -> None:
    interface = NagaControlInterface(Service())

    assert asyncio.run(interface.begin_calibration_state()) is True
    assert json.loads(interface.snapshot_document())["calibrating"] is True
    assert asyncio.run(interface.end_calibration_state()) is False
    assert json.loads(interface.snapshot_document())["calibrating"] is False


def test_dbus_interface_serializes_the_snapshot_and_releases_outputs() -> None:
    service = Service()
    interface = NagaControlInterface(service)

    assert json.loads(interface.snapshot_document()) == service.snapshot()
    assert interface.name == INTERFACE_NAME
    assert BUS_NAME == "org.nagacontrol.Service1"
    assert OBJECT_PATH == "/org/nagacontrol/Service1"

    interface.release_outputs()

    assert service.released


def test_dbus_configuration_document_round_trips_through_the_parser() -> None:
    interface = NagaControlInterface(Service())

    assert interface.configuration_document() == dump_toml(default_configuration())
    assert parse_toml(interface.configuration_document()) == default_configuration()


def test_stale_revision_maps_to_a_dbus_error() -> None:
    interface = NagaControlInterface(Service())

    with pytest.raises(DBusError) as excinfo:
        asyncio.run(interface.apply_configuration(0, dump_toml(default_configuration())))

    assert excinfo.value.type == "org.nagacontrol.Service1.Error.StaleRevision"  # type: ignore[attr-defined]


def test_unknown_profile_maps_to_a_dbus_error() -> None:
    interface = NagaControlInterface(Service())

    with pytest.raises(DBusError) as excinfo:
        asyncio.run(interface.select_profile("missing"))

    assert excinfo.value.type == "org.nagacontrol.Service1.Error.UnknownProfile"  # type: ignore[attr-defined]
