"""DEBT-13: fake-only CLI error privacy, without changing exception ownership."""

import asyncio
import errno
import re
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from test_capture_cli_behavior import CliBoundary, FakeDevice
from test_capture_cli_behavior import boundary as boundary

from naga_control.adapters.evdev.discovery import EventNode, NagaConnection
from naga_control.diagnostics import capture_cli
from naga_control.diagnostics.capture import OpenedSource, open_sources

SECRET_SERIAL = "SECRET_SERIAL_SYNTHETIC_ONLY"
USB_PATH = "/sys/devices/synthetic-private-usb/secret-port"
PHYS = "usb-synthetic-private-port/input1"
FILENAME = "/synthetic-private/input/secret-source"
FILENAME2 = "/synthetic-private/input/secret-destination"
CAUSE = "SECRET_CAUSE_SYNTHETIC_ONLY"
CONTEXT = "SECRET_CONTEXT_SYNTHETIC_ONLY"
PAYLOAD = f"{SECRET_SERIAL} {USB_PATH} {PHYS}"
SECRETS = (SECRET_SERIAL, USB_PATH, PHYS, FILENAME, FILENAME2, CAUSE, CONTEXT)


class RenderSpyOSError(OSError):
    str_calls = 0
    repr_calls = 0

    def __str__(self) -> str:
        self.str_calls += 1
        return super().__str__()

    def __repr__(self) -> str:
        self.repr_calls += 1
        return super().__repr__()


class RenderSpyPermissionError(RenderSpyOSError, PermissionError):
    pass


def private_error(permission: bool = False) -> RenderSpyOSError:
    kind = RenderSpyPermissionError if permission else RenderSpyOSError
    error = kind(errno.EACCES if permission else errno.EIO, PAYLOAD, FILENAME, None, FILENAME2)
    error.__cause__ = OSError(CAUSE + PAYLOAD, FILENAME)
    error.__context__ = RuntimeError(CONTEXT + PAYLOAD + FILENAME2)
    return error


@pytest.fixture(autouse=True)
def unprivileged_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capture_cli.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(sys, "argv", ["naga-control-capture"])


def inject_failure(
    boundary: CliBoundary,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
    error: Exception,
) -> None:
    if phase.startswith("discovery"):
        calls = 0
        fail_at = 1 if phase == "discovery-first" else 2

        def discover() -> tuple[NagaConnection, ...]:
            nonlocal calls
            calls += 1
            boundary.calls.append("discover")
            if calls == fail_at:
                raise error
            return (boundary.connection,)

        monkeypatch.setattr(capture_cli, "discover_naga_connections", discover)
    elif phase == "open":
        assert isinstance(error, OSError)
        boundary.open_error = error
    elif phase == "identity":

        def factory(path: str, readonly: bool = False) -> FakeDevice:
            assert readonly and path == boundary.connection.nodes[0].event_path
            boundary.calls.append("open")
            return boundary.devices[0]

        def identity(_number: int) -> EventNode:
            boundary.calls.append("identity")
            raise error

        def opened(connection: NagaConnection) -> tuple[OpenedSource, ...]:
            return open_sources(
                connection,
                device_factory=factory,
                identity_resolver=identity,
                device_number_resolver=lambda fd: fd,
            )

        monkeypatch.setattr(capture_cli, "open_sources", opened)
    elif phase == "metadata":

        def info(_device: FakeDevice) -> object:
            boundary.calls.append("metadata")
            raise error

        monkeypatch.setattr(FakeDevice, "info", property(info))
    elif phase == "capture":
        # A propagated capture failure retains main's existing exit policy.
        boundary.capture_error = error
    else:
        assert phase == "close"
        boundary.devices[0].close_error = error


def assert_private(text: str) -> None:
    assert all(secret not in text for secret in SECRETS)


def assert_diagnostic(text: str, error: RenderSpyOSError) -> None:
    permission = isinstance(error, PermissionError)
    assert ("Permission denied" if permission else "Input device error") in text
    assert type(error).__name__ in text
    if type(error.errno) is int:
        assert re.search(rf"(?<!\d){error.errno}(?!\d)", text)
        name = errno.errorcode.get(error.errno)
        if name is not None:
            assert name in text
    assert ("do not run as root" in text) is permission
    assert_private(text)
    assert (error.str_calls, error.repr_calls) == (0, 0)


PHASES = ("discovery-first", "discovery-second", "open", "identity", "metadata", "capture", "close")


@pytest.mark.parametrize("phase", PHASES)
@pytest.mark.parametrize("permission", [False, True])
@pytest.mark.parametrize("include_identifiers", [False, True])
def test_main_io_failures_report_safe_class_errno_and_permission_advice(
    boundary: CliBoundary,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    phase: str,
    permission: bool,
    include_identifiers: bool,
) -> None:
    error = private_error(permission)
    inject_failure(boundary, monkeypatch, phase, error)
    argv = ["naga-control-capture"] + (["--include-identifiers"] if include_identifiers else [])
    monkeypatch.setattr(sys, "argv", argv)

    assert capture_cli.main() == 2

    output = capsys.readouterr()
    assert_private(output.out + output.err)
    assert_diagnostic(output.err, error)
    expected_closes = (
        [0, 0]
        if phase.startswith("discovery") or phase == "open"
        else [1, 0]
        if phase == "identity"
        else [1, 1]
    )
    assert [device.close_count for device in boundary.devices] == expected_closes
    if phase.startswith("discovery"):
        assert boundary.calls == ["discover"] * (1 if phase.endswith("first") else 2)


@pytest.mark.parametrize("phase", PHASES)
def test_run_preserves_original_io_exception_and_chain(
    boundary: CliBoundary,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    phase: str,
) -> None:
    error = private_error()
    cause, context = error.__cause__, error.__context__
    inject_failure(boundary, monkeypatch, phase, error)

    with pytest.raises(RenderSpyOSError) as raised:
        asyncio.run(capture_cli.run(capture_cli.build_parser().parse_args([])))

    assert raised.value is error
    assert error.__cause__ is cause and error.__context__ is context
    assert (error.str_calls, error.repr_calls) == (0, 0)
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("permission", [False, True])
@pytest.mark.parametrize("entrypoint", ["main", "run"])
@pytest.mark.parametrize("phase", ["identity", "metadata", "capture"])
def test_primary_failure_survives_sensitive_close_failure(
    boundary: CliBoundary,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    permission: bool,
    entrypoint: str,
    phase: str,
) -> None:
    primary = private_error(permission)
    secondary = private_error(not permission)
    boundary.devices[0].close_error = secondary
    inject_failure(boundary, monkeypatch, phase, primary)

    if entrypoint == "main":
        assert capture_cli.main() == 2
    else:
        with pytest.raises(RenderSpyOSError) as raised:
            asyncio.run(capture_cli.run(capture_cli.build_parser().parse_args([])))
        assert raised.value is primary

    output = capsys.readouterr()
    assert_private(output.out + output.err)
    if entrypoint == "main":
        assert_diagnostic(output.err, primary)
    else:
        assert output.err == ""
    assert secondary.__context__ is primary
    assert (secondary.str_calls, secondary.repr_calls) == (0, 0)
    assert [device.close_count for device in boundary.devices] == (
        [1, 0] if phase == "identity" else [1, 1]
    )


@pytest.mark.parametrize(
    "number", [None, errno.EIO, 987654, "private-errno-" + SECRET_SERIAL, True]
)
def test_main_missing_unknown_or_invalid_errno_never_renders_payload(
    boundary: CliBoundary,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    number: int | str | None,
) -> None:
    error = private_error()
    monkeypatch.setattr(error, "errno", number)
    inject_failure(boundary, monkeypatch, "discovery-first", error)

    assert capture_cli.main() == 2

    output = capsys.readouterr()
    assert output.out == ""
    assert_diagnostic(output.err, error)


def test_main_identity_mismatch_does_not_print_generated_filename(
    boundary: CliBoundary,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = boundary.connection.nodes[0]
    boundary.connection = replace(boundary.connection, nodes=(replace(first, event_path=FILENAME),))

    def opened(connection: NagaConnection) -> tuple[OpenedSource, ...]:
        return open_sources(
            connection,
            device_factory=lambda path, readonly=False: boundary.devices[0],
            identity_resolver=lambda number: replace(first, usb_path=USB_PATH),
            device_number_resolver=lambda fd: fd,
        )

    monkeypatch.setattr(capture_cli, "open_sources", opened)

    assert capture_cli.main() == 2

    output = capsys.readouterr()
    assert output.out == ""
    assert "Input device error" in output.err and "OSError" in output.err
    assert "do not run as root" not in output.err
    assert_private(output.err)
    assert [device.close_count for device in boundary.devices] == [1, 0]


@pytest.mark.parametrize("permission", [False, True])
@pytest.mark.parametrize("entrypoint", ["main", "run"])
def test_output_error_keeps_user_path_and_class_but_not_exception_payload(
    boundary: CliBoundary,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    permission: bool,
    entrypoint: str,
) -> None:
    # A user's explicit output path is intentionally not globally sanitized.
    output_path = tmp_path / "user-selected-private-port.json"
    original = private_error(permission)

    def denied(path: Path, *_args: object, **_kwargs: object) -> int:
        assert path == output_path
        raise original

    monkeypatch.setattr(Path, "write_text", denied)
    argv = ["--list", "--output", str(output_path)]
    monkeypatch.setattr(sys, "argv", ["naga-control-capture", *argv])
    if entrypoint == "main":
        assert capture_cli.main() == 2
    else:
        with pytest.raises(capture_cli.CaptureOutputError) as raised:
            asyncio.run(capture_cli.run(capture_cli.build_parser().parse_args(argv)))
        assert raised.value.__cause__ is original
        assert str(raised.value) == f"{output_path}: {type(original).__name__}"

    output = capsys.readouterr()
    summary = type(original).__name__ + (" (errno 13 EACCES)" if permission else " (errno 5 EIO)")
    assert output.err == (
        f"Capture output error: {output_path}: {summary}\n" if entrypoint == "main" else ""
    )
    assert_private(output.out + output.err)
    assert "do not run as root" not in output.err
    assert (original.str_calls, original.repr_calls) == (0, 0)
    assert [device.close_count for device in boundary.devices] == [1, 1]
    assert not output_path.exists()


@pytest.mark.parametrize(
    "phase", ["discovery-first", "discovery-second", "identity", "metadata", "capture", "close"]
)
def test_main_does_not_blanket_catch_non_io_failures(
    boundary: CliBoundary,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    phase: str,
) -> None:
    original = RuntimeError(PAYLOAD)
    inject_failure(boundary, monkeypatch, phase, original)

    with pytest.raises(RuntimeError) as raised:
        capture_cli.main()

    assert raised.value is original
    assert capsys.readouterr().err == ""
