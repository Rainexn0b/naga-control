import json
import sys
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

import pytest

from naga_control.adapters.evdev.discovery import EventNode, NagaConnection
from naga_control.diagnostics import capture_cli
from naga_control.diagnostics.capture import (
    CaptureResult,
    EventRecord,
    FrameRecord,
    InputEventLike,
    OpenedSource,
    open_sources,
)

SERIAL = "SYNTHETIC-SERIAL-001"
USB_PATH = "/sys/devices/pci0000:00/0000:00:14.0/usb1/1-9"
PHYSICAL_PATH = "pci-0000:00:14.0-usb-0:9"
PHYS = "usb-0000:00:14.0-9/input1"
UNIQ = "SYNTHETIC-UNIQ-002"
FRAME = FrameRecord(
    "interface-01",
    (
        EventRecord(10, 20, 4, "EV_MSC", 4, "MSC_SCAN", 458860),
        EventRecord(10, 21, 1, "EV_KEY", 187, "KEY_F17", 1),
        EventRecord(10, 22, 0, "EV_SYN", 0, "SYN_REPORT", 0),
    ),
)


@dataclass(frozen=True)
class DeviceInfo:
    bustype: int = 3
    vendor: int = 0x1532
    product: int = 0x00E8
    version: int = 0x0100


@dataclass
class FakeDevice:
    fd: int
    close_count: int = 0
    close_error: BaseException | None = None
    name = "Razer Naga V3 Pro"
    phys = PHYS
    uniq = UNIQ
    info = DeviceInfo()

    def close(self) -> None:
        self.close_count += 1
        if self.close_error is not None:
            raise self.close_error

    def input_props(self, verbose: bool = False) -> list[int]:
        assert not verbose
        return [0]

    def capabilities(self, verbose: bool = False, absinfo: bool = True) -> dict[int, list[int]]:
        assert not verbose and absinfo
        return {1: [187], 4: [4]}

    async def async_read_loop(self) -> AsyncIterator[InputEventLike]:
        raise AssertionError("CLI capture must use the injected frame reader")
        yield


@dataclass
class CliBoundary:
    connection: NagaConnection
    devices: tuple[FakeDevice, ...]
    calls: list[str] = field(default_factory=lambda: list[str]())
    capture_duration: float | None = None
    open_error: OSError | None = None
    capture_error: BaseException | None = None
    identity_mismatch: bool = False


@pytest.fixture
def boundary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> CliBoundary:
    nodes = tuple(
        EventNode(str(tmp_path / f"event-{i}"), USB_PATH, i, "1532", "00e8", SERIAL)
        for i in ("01", "02")
    )
    state = CliBoundary(
        NagaConnection(USB_PATH, "1532", "00e8", "hyperspeed", SERIAL, PHYSICAL_PATH, nodes),
        (FakeDevice(0), FakeDevice(1)),
    )

    def discover() -> tuple[NagaConnection, ...]:
        state.calls.append("discover")
        return (state.connection,)

    def factory(path: str, readonly: bool = False) -> FakeDevice:
        state.calls.append("open")
        assert readonly
        if state.open_error is not None:
            raise state.open_error
        return state.devices[next(i for i, node in enumerate(nodes) if node.event_path == path)]

    def identity(number: int) -> EventNode:
        node = nodes[number]
        return replace(node, usb_path=USB_PATH + "-unrelated") if state.identity_mismatch else node

    def opened(connection: NagaConnection) -> tuple[OpenedSource, ...]:
        return open_sources(
            connection,
            device_factory=factory,
            identity_resolver=identity,
            device_number_resolver=lambda fd: fd,
        )

    async def capture(
        sources: tuple[OpenedSource, ...],
        duration: float,
        on_frame: Callable[[FrameRecord], None],
    ) -> CaptureResult:
        state.calls.append("capture")
        state.capture_duration = duration
        assert tuple(source.source_id for source in sources) == ("interface-01", "interface-02")
        assert tuple(source.device for source in sources) == state.devices
        if state.capture_error is not None:
            raise state.capture_error
        on_frame(FRAME)
        return CaptureResult((FRAME,), "duration elapsed")

    monkeypatch.setattr(capture_cli, "discover_naga_connections", discover)
    monkeypatch.setattr(capture_cli, "open_sources", opened)
    monkeypatch.setattr(capture_cli, "capture_frames", capture)

    def fake_version(name: str) -> str:
        assert name == "evdev"
        return "2.0-fake"

    monkeypatch.setattr(capture_cli, "version", fake_version)
    monkeypatch.setattr(capture_cli.platform, "release", lambda: "fake-kernel")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(sys, "argv", ["naga-control-capture"])
    return state


@pytest.mark.parametrize("value", ["0", "-0.01", "not-a-number"])
def test_invalid_duration_exits_before_discovery(
    boundary: CliBoundary,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    value: str,
) -> None:
    monkeypatch.setattr(sys, "argv", ["naga-control-capture", "--duration", value])
    with pytest.raises(SystemExit) as raised:
        capture_cli.main()
    assert raised.value.code == 2
    output = capsys.readouterr()
    assert output.out == "" and "--duration" in output.err
    assert boundary.calls == []


@pytest.mark.parametrize("listing", [False, True])
@pytest.mark.parametrize("write_file", [False, True])
@pytest.mark.parametrize("include_identifiers", [False, True])
@pytest.mark.parametrize("duration", [None, 0.25])
def test_dispatch_text_and_json_contract(
    boundary: CliBoundary,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    listing: bool,
    write_file: bool,
    include_identifiers: bool,
    duration: float | None,
) -> None:
    output_path = tmp_path / "capture.json"
    argv = ["naga-control-capture"]
    argv += ["--list"] if listing else []
    argv += ["--output", str(output_path)] if write_file else []
    argv += ["--include-identifiers"] if include_identifiers else []
    argv += ["--duration", str(duration)] if duration is not None else []
    monkeypatch.setattr(sys, "argv", argv)
    assert capture_cli.main() == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert "Razer Naga V3 Pro: hyperspeed, 1532:00e8" in output.out
    assert "Live event paths (not persisted):" in output.out
    assert all(node.event_path in output.out for node in boundary.connection.nodes)
    text_metadata = json.loads(output.out.split("\n", 1)[1].split("\nLive event paths")[0])
    assert text_metadata["serial"] == (SERIAL if include_identifiers else "<redacted>")
    assert text_metadata["physical_path"] == (
        PHYSICAL_PATH if include_identifiers else "<redacted>"
    )
    assert text_metadata["nodes"][0]["phys"] == (PHYS if include_identifiers else "<redacted>")
    assert text_metadata["nodes"][0]["uniq"] == (UNIQ if include_identifiers else "<redacted>")
    assert boundary.calls[:2] == ["discover", "discover"]
    assert all(device.close_count == 1 for device in boundary.devices)
    assert boundary.calls[2:4] == ["open", "open"]
    if listing:
        assert "capture" not in boundary.calls
        assert "Capturing" not in output.out
        assert "KEY_F17" not in output.out.split("Live event paths")[1]
    else:
        expected_duration = 30.0 if duration is None else duration
        assert boundary.calls[-1] == "capture" and boundary.capture_duration == expected_duration
        assert f"Capturing complete frames for {expected_duration:g} seconds" in output.out
        assert (
            "interface-01: EV_MSC/MSC_SCAN=458860 (0x7006c), EV_KEY/KEY_F17=1, EV_SYN/SYN_REPORT=0"
            in output.out
        )
        assert "Capture ended: duration elapsed (1 frames)" in output.out
    assert output_path.exists() is write_file
    if write_file:
        raw = output_path.read_text(encoding="utf-8")
        document = json.loads(raw)
        assert raw.endswith("\n") and document["schema_version"] == 1
        assert datetime.fromisoformat(document["captured_at"]).utcoffset() is not None
        assert document["device"] == text_metadata
        assert document["environment"] == dict(
            kernel="fake-kernel",
            python_evdev="2.0-fake",
            openrazer_revision="unknown",
            firmware="unknown",
            driver_mode="unknown",
            desktop="console",
            plate="unknown",
        )
        assert document["frames"] == ([] if listing else [FRAME.as_json()])
        assert document["end_reason"] == ("listing only" if listing else "duration elapsed")
        assert all(node.event_path not in raw for node in boundary.connection.nodes)
        assert f"Wrote {output_path}" in output.out
        if not include_identifiers:
            assert all(
                secret not in raw + output.out
                for secret in (SERIAL, USB_PATH, PHYSICAL_PATH, PHYS, UNIQ)
            )


@pytest.mark.parametrize("phase", [0, 1, 2])
def test_empty_discovery_or_uninitialized_nodes_do_not_open(
    boundary: CliBoundary,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    phase: int,
) -> None:
    snapshots = iter([(boundary.connection,)] * phase + [()])
    if phase == 2:
        boundary.connection = replace(boundary.connection, nodes=())
    else:
        monkeypatch.setattr(capture_cli, "discover_naga_connections", lambda: next(snapshots))
    assert capture_cli.main() == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == (
        "The Naga USB device has no initialized event nodes.\n"
        if phase == 2
        else "No supported Naga V3 Pro USB connection found.\n"
    )
    assert all(device.close_count == 0 for device in boundary.devices)
    assert "open" not in boundary.calls


@pytest.mark.parametrize(
    "wayland,display,expected",
    [("wayland-0", ":0", "wayland"), ("", ":0", "xorg"), ("", "", "console")],
)
def test_desktop_detection(
    boundary: CliBoundary,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    wayland: str,
    display: str,
    expected: str,
) -> None:
    monkeypatch.setenv("WAYLAND_DISPLAY", wayland)
    monkeypatch.setenv("DISPLAY", display)
    output = tmp_path / "desktop.json"
    monkeypatch.setattr(sys, "argv", ["naga-control-capture", "--list", "--output", str(output)])
    assert capture_cli.main() == 0
    assert json.loads(output.read_text(encoding="utf-8"))["environment"]["desktop"] == expected
    assert "capture" not in boundary.calls
