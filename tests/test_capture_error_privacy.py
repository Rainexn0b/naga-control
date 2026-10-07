"""DEBT-13: error payloads stay private even when metadata identifiers are opted in."""

import argparse
import asyncio
import builtins
import json
import sys
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

import pytest
from test_capture_cli_behavior import (
    FRAME,
    PHYS,
    PHYSICAL_PATH,
    SERIAL,
    UNIQ,
    CliBoundary,
    FakeDevice,
)
from test_capture_cli_behavior import boundary as boundary

from naga_control.diagnostics import capture_cli
from naga_control.diagnostics.capture import (
    CaptureResult,
    FrameRecord,
    InputEventLike,
    capture_frames,
    connection_metadata,
)

ERROR_PAYLOAD = "ErrorPayload SECRET_SERIAL /sys/usb/SECRET_PORT"
ERROR_FILENAME = "/sys/usb/SECRET_PORT/SECRET_SERIAL"
ERROR_FILENAME2 = "/sys/usb/SECRET_PORT/SECRET_SECOND_FILENAME"
ERROR_CAUSE = "SECRET_CAUSE ErrorPayload"
ERROR_CONTEXT = "SECRET_CONTEXT ErrorPayload"
ERROR_TOKENS = (
    "ErrorPayload",
    "SECRET_SERIAL",
    "SECRET_PORT",
    "SECRET_SECOND_FILENAME",
    "SECRET_CAUSE",
    "SECRET_CONTEXT",
)
RENDER_CALLS: list[str] = []


class RenderSpy:
    def __str__(self) -> str:
        RENDER_CALLS.append("exception str")
        return ERROR_PAYLOAD + ERROR_FILENAME + ERROR_FILENAME2 + ERROR_CAUSE + ERROR_CONTEXT

    def __repr__(self) -> str:
        RENDER_CALLS.append("exception repr")
        return ERROR_PAYLOAD


# Conventional exception names keep the tests independent of a custom-name policy.
class OSError(RenderSpy, builtins.OSError):
    pass


class PermissionError(RenderSpy, builtins.PermissionError):
    pass


class NumericPayload(int):
    def __str__(self) -> str:
        RENDER_CALLS.append("errno str")
        raise AssertionError("errno subclass must not be rendered")

    def __repr__(self) -> str:
        RENDER_CALLS.append("errno repr")
        raise AssertionError("errno subclass must not be rendered")

    def __format__(self, format_spec: str) -> str:
        RENDER_CALLS.append("errno format")
        raise AssertionError("errno subclass must not be formatted")


def sensitive_error(
    error_type: type[builtins.OSError], number: object, monkeypatch: pytest.MonkeyPatch
) -> builtins.OSError:
    RENDER_CALLS.clear()
    error = error_type(19, ERROR_PAYLOAD, ERROR_FILENAME, None, ERROR_FILENAME2)
    monkeypatch.setattr(error, "errno", number)
    error.__cause__ = RuntimeError(ERROR_CAUSE)
    error.__context__ = RuntimeError(ERROR_CONTEXT)
    return error


@dataclass(frozen=True)
class Event:
    sec: int
    usec: int
    type: int
    code: int
    value: int


EVENTS = tuple(
    Event(event.seconds, event.microseconds, event.event_type, event.code, event.value)
    for event in FRAME.events
)
RELEASE_EVENTS = (EVENTS[0], replace(EVENTS[1], value=0), EVENTS[2])
RELEASE_FRAME = replace(
    FRAME, events=(FRAME.events[0], replace(FRAME.events[1], value=0), FRAME.events[2])
)


class StreamingDevice(FakeDevice):
    def __init__(self, fd: int, reader: Callable[[], AsyncIterator[InputEventLike]]) -> None:
        super().__init__(fd)
        self.reader = reader

    def async_read_loop(self) -> AsyncIterator[InputEventLike]:
        return self.reader()


def stream_failure(boundary: CliBoundary, error: builtins.OSError) -> list[str]:
    trace: list[str] = []

    async def failed() -> AsyncIterator[InputEventLike]:
        try:
            for event in (*EVENTS, *RELEASE_EVENTS, EVENTS[0]):
                yield event
            raise error
        finally:
            trace.append("failed finalized")

    async def sibling() -> AsyncIterator[InputEventLike]:
        try:
            for event in EVENTS:
                yield event
            await asyncio.Event().wait()
        finally:
            trace.append("sibling finalized")

    boundary.devices = (StreamingDevice(0, failed), StreamingDevice(1, sibling))
    return trace


def assert_private(text: str) -> None:
    assert all(token not in text for token in ERROR_TOKENS)


def assert_reason(reason: str, error_type: type[builtins.OSError], number: object) -> None:
    assert "interface-01" in reason and "read failed" in reason
    assert error_type.__name__ in reason
    if type(number) is int and number in (19, 13):
        assert f"errno {number}" in reason
    assert_private(reason)


def assert_metadata(metadata: dict[str, object], include_identifiers: bool) -> None:
    # Only these metadata fields are redacted; frames and live event paths are not private.
    assert metadata["serial"] == (SERIAL if include_identifiers else "<redacted>")
    assert metadata["physical_path"] == (PHYSICAL_PATH if include_identifiers else "<redacted>")
    nodes = cast(list[dict[str, object]], metadata["nodes"])
    for node in nodes:
        assert node["phys"] == (PHYS if include_identifiers else "<redacted>")
        assert node["uniq"] == (UNIQ if include_identifiers else "<redacted>")


@pytest.mark.parametrize("error_type", [OSError, PermissionError])
@pytest.mark.parametrize("include_identifiers", [False, True])
@pytest.mark.parametrize(
    "number",
    [19, 13, None, ERROR_PAYLOAD, True, 10**100, NumericPayload(19)],
    ids=["enodev", "eacces", "none", "invalid-string", "bool", "unknown-huge", "int-subclass"],
)
async def test_actual_reader_reason_and_written_json_never_render_error_payloads(
    boundary: CliBoundary,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    error_type: type[builtins.OSError],
    include_identifiers: bool,
    number: object,
) -> None:
    error = sensitive_error(error_type, number, monkeypatch)
    trace = stream_failure(boundary, error)
    sources = capture_cli.open_sources(boundary.connection)
    observed: list[FrameRecord] = []
    result = await asyncio.wait_for(capture_frames(sources, 30, observed.append), 2)
    assert result.frames == (FRAME, RELEASE_FRAME, replace(FRAME, source="interface-02"))
    assert result.frames == tuple(observed)
    assert trace == ["failed finalized", "sibling finalized"]
    assert [device.close_count for device in boundary.devices] == [0, 0]
    metadata = connection_metadata(
        boundary.connection, sources, include_identifiers=include_identifiers
    )
    assert_metadata(metadata, include_identifiers)
    argv = ["--include-identifiers"] if include_identifiers else []
    args = capture_cli.build_parser().parse_args(argv)
    output = tmp_path / "capture.json"
    capture_cli._write_capture(output, args, metadata, result)  # pyright: ignore[reportPrivateUsage]
    raw = output.read_text(encoding="utf-8")
    document = json.loads(raw)
    assert document["end_reason"] == result.end_reason
    assert document["frames"] == [frame.as_json() for frame in result.frames]
    assert document["device"] == metadata
    assert raw.endswith("\n") and document["schema_version"] == 1
    assert_private(raw)
    assert_reason(result.end_reason, error_type, number)
    assert RENDER_CALLS == []


@pytest.mark.parametrize("error_type,number", [(OSError, 19), (PermissionError, 13)])
@pytest.mark.parametrize("include_identifiers", [False, True])
def test_read_failure_keeps_normal_end_context_exit_zero_and_run_owned_close(
    boundary: CliBoundary,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    error_type: type[builtins.OSError],
    number: int,
    include_identifiers: bool,
) -> None:
    trace = stream_failure(boundary, sensitive_error(error_type, number, monkeypatch))
    monkeypatch.setattr(capture_cli, "capture_frames", capture_frames)
    original_close = capture_cli.close_sources

    def closed(sources: tuple[capture_cli.OpenedSource, ...]) -> None:
        assert trace == ["failed finalized", "sibling finalized"]
        original_close(sources)
        trace.append("owner closed")

    monkeypatch.setattr(capture_cli, "close_sources", closed)
    output = tmp_path / "capture.json"
    argv = ["--output", str(output)] + (["--include-identifiers"] if include_identifiers else [])
    monkeypatch.setattr(sys, "argv", ["naga-control-capture", *argv])

    # main() still owns asyncio.run(); the injected runner adds only a finite test bound.
    original_run = capture_cli.run

    async def bounded(args: argparse.Namespace) -> int:
        return await asyncio.wait_for(original_run(args), 2)

    monkeypatch.setattr(capture_cli, "run", bounded)
    status = capture_cli.main()
    text = capsys.readouterr()
    assert status == 0 and text.err == ""
    assert trace[-1] == "owner closed"
    assert [device.close_count for device in boundary.devices] == [1, 1]
    document = json.loads(output.read_text(encoding="utf-8"))
    assert len(document["frames"]) == 3
    reason = document["end_reason"]
    assert f"Capture ended: {reason} (3 frames)" in text.out
    assert "Capturing complete frames" in text.out and f"Wrote {output}" in text.out
    assert "EV_KEY/KEY_F17=1" in text.out
    text_metadata = json.loads(text.out.split("\n", 1)[1].split("\nLive event paths")[0])
    assert text_metadata == document["device"]
    assert_metadata(document["device"], include_identifiers)
    assert_private(text.out + output.read_text(encoding="utf-8"))
    assert_reason(reason, error_type, number)
    assert RENDER_CALLS == []


@pytest.mark.parametrize(
    "error_type,number,phase",
    [
        (OSError, 19, "Input device error:"),
        (PermissionError, 13, "Permission denied:"),
    ],
)
@pytest.mark.parametrize("include_identifiers", [False, True])
def test_input_open_failure_remains_exit_two_without_error_payload(
    boundary: CliBoundary,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    error_type: type[builtins.OSError],
    number: int,
    phase: str,
    include_identifiers: bool,
) -> None:
    boundary.open_error = sensitive_error(error_type, number, monkeypatch)
    output = tmp_path / "not-written.json"
    argv = ["naga-control-capture", "--output", str(output)]
    argv += ["--include-identifiers"] if include_identifiers else []
    monkeypatch.setattr(sys, "argv", argv)
    assert capture_cli.main() == 2
    text = capsys.readouterr()
    assert text.out == "" and phase in text.err
    assert not output.exists()
    assert [device.close_count for device in boundary.devices] == [0, 0]
    if error_type is PermissionError:
        assert "scoped udev rule" in text.err and "do not run as root" in text.err
    assert_private(text.err)
    assert error_type.__name__ in text.err and f"errno {number}" in text.err
    assert RENDER_CALLS == []


async def test_failure_drains_queued_sibling_frames_and_joins_async_finalizer(
    boundary: CliBoundary,
) -> None:
    finalizing, release, joined = (asyncio.Event() for _ in range(3))

    async def failing() -> AsyncIterator[InputEventLike]:
        for event in (*EVENTS, EVENTS[0]):
            yield event
        raise builtins.OSError(19, "synthetic disconnect")

    async def sibling() -> AsyncIterator[InputEventLike]:
        try:
            # The failure marker is queued before these complete sibling frames.
            for event in (*EVENTS, *RELEASE_EVENTS, EVENTS[0]):
                yield event
            await asyncio.Event().wait()
        finally:
            finalizing.set()
            await release.wait()
            joined.set()

    boundary.devices = (StreamingDevice(0, failing), StreamingDevice(1, sibling))
    sources = capture_cli.open_sources(boundary.connection)
    observed: list[FrameRecord] = []

    async def exercise() -> CaptureResult:
        task = asyncio.create_task(capture_frames(sources, 30, observed.append))
        try:
            await finalizing.wait()
            assert not task.done() and not joined.is_set()
            release.set()
            return await task
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    result = await asyncio.wait_for(exercise(), 2)
    assert joined.is_set()
    assert result.frames == (
        FRAME,
        replace(FRAME, source="interface-02"),
        replace(RELEASE_FRAME, source="interface-02"),
    )
    assert result.frames == tuple(observed)
    assert [device.close_count for device in boundary.devices] == [0, 0]
