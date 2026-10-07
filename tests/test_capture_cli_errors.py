"""CLI failure diagnostics and primary-versus-cleanup exception contracts."""

import asyncio
import sys
from pathlib import Path

import pytest
from test_capture_cli_behavior import PHYS, SERIAL, UNIQ, USB_PATH, CliBoundary
from test_capture_cli_behavior import boundary as boundary

from naga_control.diagnostics import capture_cli


@pytest.mark.parametrize("failure", ["permission", "open", "identity", "interrupt"])
def test_capture_failures_exit_and_close_owned_descriptors(
    boundary: CliBoundary,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    failure: str,
) -> None:
    output_path = tmp_path / "not-written.json"
    monkeypatch.setattr(sys, "argv", ["naga-control-capture", "--output", str(output_path)])
    if failure == "permission":
        boundary.open_error = PermissionError("fake access denied")
    elif failure == "open":
        boundary.open_error = OSError("fake source vanished")
    elif failure == "identity":
        boundary.identity_mismatch = True
    else:
        boundary.capture_error = KeyboardInterrupt()
    assert capture_cli.main() == (130 if failure == "interrupt" else 2)
    output = capsys.readouterr()
    expected = {
        "permission": "Permission denied: PermissionError",
        "open": "Input device error: OSError",
        "identity": "Input device error: OSError",
        "interrupt": "Capture interrupted; no JSON file was written.",
    }
    assert expected[failure] in output.err
    if failure == "permission":
        assert "do not run as root" in output.err
    assert [device.close_count for device in boundary.devices] == (
        {"permission": [0, 0], "open": [0, 0], "identity": [1, 0], "interrupt": [1, 1]}[failure]
    )
    assert "Capture ended:" not in output.out and "Wrote " not in output.out
    assert not output_path.exists()


@pytest.mark.parametrize("listing", [False, True])
@pytest.mark.parametrize("failure", ["permission", "directory", "write"])
@pytest.mark.parametrize("entrypoint", ["main", "run"])
def test_output_write_errors_exit_and_close_sources(
    boundary: CliBoundary,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    listing: bool,
    failure: str,
    entrypoint: str,
) -> None:
    output_path = tmp_path if failure == "directory" else tmp_path / "capture.json"
    original = (
        PermissionError(SERIAL + USB_PATH + PHYS + UNIQ)
        if failure == "permission"
        else OSError(SERIAL + USB_PATH + PHYS + UNIQ)
    )
    if failure != "directory":

        def denied(path: Path, *_args: object, **_kwargs: object) -> int:
            assert path == output_path
            raise original

        monkeypatch.setattr(Path, "write_text", denied)
    argv = ["naga-control-capture", "--output", str(output_path)] + (["--list"] if listing else [])
    monkeypatch.setattr(sys, "argv", argv)
    label = {"permission": "PermissionError", "directory": "IsADirectoryError", "write": "OSError"}[
        failure
    ]
    if entrypoint == "main":
        assert capture_cli.main() == 2
    else:
        with pytest.raises(capture_cli.CaptureOutputError) as raised:
            asyncio.run(capture_cli.run(capture_cli.build_parser().parse_args(argv[1:])))
        assert str(raised.value) == f"{output_path}: {label}"
        assert isinstance(raised.value.__cause__, OSError)
        if failure != "directory":
            assert raised.value.__cause__ is original
    output = capsys.readouterr()
    summary = label + (" (errno 21 EISDIR)" if failure == "directory" else "")
    assert output.err == (
        f"Capture output error: {output_path}: {summary}\n" if entrypoint == "main" else ""
    )
    assert all(secret not in output.out + output.err for secret in (SERIAL, USB_PATH, PHYS, UNIQ))
    assert "Input device error" not in output.err and "udev" not in output.err
    assert "Wrote " not in output.out
    assert all(device.close_count == 1 for device in boundary.devices)
    assert not (tmp_path / "capture.json").exists()


@pytest.mark.parametrize("primary", ["output", "interrupt"])
@pytest.mark.parametrize("close_type", [PermissionError, OSError, RuntimeError])
@pytest.mark.parametrize("entrypoint", ["main", "run"])
def test_body_failure_survives_ordinary_close_failure(
    boundary: CliBoundary,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    primary: str,
    close_type: type[Exception],
    entrypoint: str,
) -> None:
    output_path = tmp_path / "capture.json"
    original = PermissionError("private output payload")
    interruption = KeyboardInterrupt("primary interruption")
    secondary = close_type("secondary close payload")
    boundary.devices[0].close_error = secondary
    argv = ["naga-control-capture", "--output", str(output_path)]
    monkeypatch.setattr(sys, "argv", argv)
    if primary == "output":

        def denied(path: Path, *_args: object, **_kwargs: object) -> int:
            assert path == output_path
            raise original

        monkeypatch.setattr(Path, "write_text", denied)
    else:
        boundary.capture_error = interruption
    if entrypoint == "main":
        assert capture_cli.main() == (2 if primary == "output" else 130)
    else:
        expected = capture_cli.CaptureOutputError if primary == "output" else KeyboardInterrupt
        with pytest.raises(expected) as raised:
            asyncio.run(capture_cli.run(capture_cli.build_parser().parse_args(argv[1:])))
        assert raised.value is secondary.__context__
        if primary == "output":
            assert str(raised.value) == f"{output_path}: PermissionError"
            assert raised.value.__cause__ is original
        else:
            assert raised.value is interruption
    output = capsys.readouterr()
    diagnostic = (
        f"Capture output error: {output_path}: PermissionError\n"
        if primary == "output"
        else "Capture interrupted; no JSON file was written.\n"
    )
    assert output.err == (diagnostic if entrypoint == "main" else "")
    assert "udev" not in output.err and "Input device error" not in output.err
    assert "payload" not in output.out + output.err and "Wrote " not in output.out
    assert [device.close_count for device in boundary.devices] == [1, 1]
    assert not output_path.exists()


@pytest.mark.parametrize("listing", [False, True])
@pytest.mark.parametrize("close_type", [PermissionError, OSError, RuntimeError])
@pytest.mark.parametrize("entrypoint", ["main", "run"])
def test_standalone_close_failure_remains_observable(
    boundary: CliBoundary,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    listing: bool,
    close_type: type[Exception],
    entrypoint: str,
) -> None:
    original = close_type("standalone close failure")
    boundary.devices[0].close_error = original
    argv = ["naga-control-capture"] + (["--list"] if listing else [])
    monkeypatch.setattr(sys, "argv", argv)
    if entrypoint == "main" and isinstance(original, OSError):
        assert capture_cli.main() == 2
        expected = (
            "Permission denied:" if isinstance(original, PermissionError) else "Input device error:"
        )
        assert expected in capsys.readouterr().err
    else:
        with pytest.raises(close_type) as raised:
            if entrypoint == "main":
                capture_cli.main()
            else:
                asyncio.run(capture_cli.run(capture_cli.build_parser().parse_args(argv[1:])))
        assert raised.value is original
        assert capsys.readouterr().err == ""
    assert [device.close_count for device in boundary.devices] == [1, 1]


@pytest.mark.parametrize("listing", [False, True])
def test_outer_exception_context_does_not_hide_standalone_close_error(
    boundary: CliBoundary,
    listing: bool,
) -> None:
    original = RuntimeError("standalone close failure")
    boundary.devices[0].close_error = original
    args = capture_cli.build_parser().parse_args(["--list"] if listing else [])
    try:
        raise LookupError("caller exception context")
    except LookupError:
        with pytest.raises(RuntimeError) as raised:
            asyncio.run(capture_cli.run(args))
    assert raised.value is original
    assert [device.close_count for device in boundary.devices] == [1, 1]


@pytest.mark.parametrize("close_type", [KeyboardInterrupt, SystemExit])
def test_secondary_base_interruption_is_not_suppressed(
    boundary: CliBoundary,
    close_type: type[BaseException],
) -> None:
    primary = KeyboardInterrupt("primary interruption")
    secondary = close_type("secondary interruption")
    boundary.capture_error = primary
    boundary.devices[1].close_error = secondary
    with pytest.raises(close_type) as raised:
        asyncio.run(capture_cli.run(capture_cli.build_parser().parse_args([])))
    assert raised.value is secondary
    assert [device.close_count for device in boundary.devices] == [1, 1]
