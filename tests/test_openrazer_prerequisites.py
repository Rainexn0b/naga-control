import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_openrazer_backend import FakeDevice, FakeManager

from naga_control.adapters.evdev.discovery import EventNode, NagaConnection, Transport
from naga_control.adapters.openrazer import client_factory
from naga_control.adapters.openrazer.backend import OpenRazerBackend
from naga_control.domain.defaults import default_configuration
from naga_control.gui.models import parse_snapshot
from naga_control.service.snapshot import snapshot_document


def _connection(transport: Transport) -> NagaConnection:
    product_id = "00e7" if transport == "wired" else "00e8"
    return NagaConnection(
        usb_path="/usb/test",
        vendor_id="1532",
        product_id=product_id,
        transport=transport,
        serial="test-only",
        physical_path="test-only",
        nodes=(EventNode("/not-a-device", "/usb/test", "00", "1532", product_id),),
    )


@pytest.mark.parametrize("name", ["openrazer", "openrazer.client"])
def test_missing_openrazer_has_actionable_error_through_service_snapshot(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    importer = Mock(side_effect=ModuleNotFoundError("private path/serial", name=name))
    monkeypatch.setattr(client_factory, "import_module", importer)
    backend = OpenRazerBackend()
    state = backend.rescan((_connection("hyperspeed"),))

    assert state.status == "unavailable"
    assert state.transport == "hyperspeed"
    assert state.error is not None
    assert state.error.code == "openrazer_not_installed"
    assert "not installed" in state.error.message
    assert "driver, daemon and Python client" in state.error.message
    assert "AppImage does not include them" in state.error.message
    assert "private" not in state.error.message
    assert state.dpi is None
    importer.assert_called_once_with("openrazer.client")

    document = snapshot_document(
        state, default_configuration(), (), False, None, "hardware is not available", False
    )
    view = parse_snapshot(json.dumps(document))
    assert view.error_code == "openrazer_not_installed"
    assert view.error == state.error.message
    assert not view.mode_ready
    assert view.observed.dpi is None


@pytest.mark.parametrize(
    "error",
    [
        ModuleNotFoundError("private path/serial", name="dbus"),
        ModuleNotFoundError("private path/serial", name="openrazer.client.devices"),
        ModuleNotFoundError("private path/serial"),
        ImportError("private path/serial"),
    ],
)
def test_broken_import_is_not_misreported_as_openrazer_not_installed(
    monkeypatch: pytest.MonkeyPatch, error: ImportError
) -> None:
    monkeypatch.setattr(client_factory, "import_module", Mock(side_effect=error))
    state = OpenRazerBackend().rescan((_connection("wired"),))
    assert state.error is not None
    assert state.error.code == "prerequisite_unavailable"
    assert "Repair its dependencies" in state.error.message
    assert "not installed" not in state.error.message
    assert "private" not in state.error.message


@pytest.mark.parametrize("module", [SimpleNamespace(), SimpleNamespace(DeviceManager=None)])
def test_missing_or_noncallable_api_requests_client_repair(
    monkeypatch: pytest.MonkeyPatch, module: SimpleNamespace
) -> None:
    monkeypatch.setattr(client_factory, "import_module", Mock(return_value=module))
    state = OpenRazerBackend().rescan((_connection("wired"),))
    assert state.error is not None and state.error.code == "prerequisite_unavailable"


def test_daemon_failure_is_not_misreported_as_missing_installation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = SimpleNamespace(DeviceManager=Mock(side_effect=RuntimeError("daemon offline")))
    monkeypatch.setattr(client_factory, "import_module", Mock(return_value=module))
    state = OpenRazerBackend().rescan((_connection("wired"),))
    assert state.error is not None and state.error.code == "backend_unavailable"


def test_rescan_recovers_and_clears_prerequisite_code(monkeypatch: pytest.MonkeyPatch) -> None:
    module = SimpleNamespace(DeviceManager=lambda: FakeManager((FakeDevice(),)))
    importer = Mock(side_effect=[ModuleNotFoundError(name="openrazer"), module])
    monkeypatch.setattr(client_factory, "import_module", importer)
    backend = OpenRazerBackend()
    missing = backend.rescan((_connection("wired"),))
    recovered = backend.rescan((_connection("wired"),))
    assert missing.error is not None and missing.error.code == "openrazer_not_installed"
    assert recovered.status == "available"
    assert recovered.error is None
    assert snapshot_document(recovered, None, (), False, None, None, False)["error_code"] is None
