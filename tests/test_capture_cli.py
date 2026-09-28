import argparse

import pytest

from naga_control.adapters.evdev.discovery import EventNode, NagaConnection, Transport
from naga_control.diagnostics import capture_cli
from naga_control.diagnostics.capture import OpenedSource


@pytest.mark.asyncio
async def test_dual_transport_conflict_does_not_open_input_nodes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connections = (_connection("00e7", "wired"), _connection("00e8", "hyperspeed"))
    monkeypatch.setattr(capture_cli, "discover_naga_connections", lambda: connections)

    def unexpected_open(_connection: NagaConnection) -> tuple[OpenedSource, ...]:
        raise AssertionError("input nodes must not be opened during a transport conflict")

    monkeypatch.setattr(capture_cli, "open_sources", unexpected_open)

    result = await capture_cli.run(argparse.Namespace())

    assert result == 2
    assert "Multiple Naga USB connections found" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_second_discovery_catches_transport_attached_before_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshots = iter(
        (
            (_connection("00e8", "hyperspeed"),),
            (_connection("00e7", "wired"), _connection("00e8", "hyperspeed")),
        )
    )
    monkeypatch.setattr(capture_cli, "discover_naga_connections", lambda: next(snapshots))

    def unexpected_open(_connection: NagaConnection) -> tuple[OpenedSource, ...]:
        raise AssertionError("input nodes must not be opened after a transport conflict")

    monkeypatch.setattr(capture_cli, "open_sources", unexpected_open)

    assert await capture_cli.run(argparse.Namespace()) == 2


def test_capture_duration_must_be_positive() -> None:
    with pytest.raises(SystemExit):
        capture_cli.build_parser().parse_args(["--duration", "0"])


def _connection(product_id: str, transport: Transport) -> NagaConnection:
    node = EventNode(
        event_path=f"/dev/input/event-{product_id}",
        usb_path=f"/sys/devices/{product_id}",
        interface_number="00",
        vendor_id="1532",
        product_id=product_id,
    )
    return NagaConnection(
        usb_path=node.usb_path,
        vendor_id=node.vendor_id,
        product_id=node.product_id,
        transport=transport,
        serial="same-serial",
        physical_path=None,
        nodes=(node,),
    )
