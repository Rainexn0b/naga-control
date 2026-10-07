"""Trusted capture error fields, bounded errno, and hostile subclass boundaries."""

import argparse
import errno
from pathlib import Path

import pytest
from test_capture_cli_behavior import CliBoundary
from test_capture_cli_behavior import boundary as boundary
from test_capture_cli_error_privacy import (
    FILENAME,
    PAYLOAD,
    SECRET_SERIAL,
    assert_private,
    inject_failure,
    private_error,
)
from test_capture_cli_error_privacy import unprivileged_argv as unprivileged_argv

from naga_control.diagnostics import capture, capture_cli


class NumericSpy(int):
    str_calls = 0
    repr_calls = 0
    format_calls = 0
    int_calls = 0

    def __str__(self) -> str:
        self.str_calls += 1
        return SECRET_SERIAL

    def __repr__(self) -> str:
        self.repr_calls += 1
        return SECRET_SERIAL

    def __format__(self, format_spec: str) -> str:
        self.format_calls += 1
        return SECRET_SERIAL

    def __int__(self) -> int:
        self.int_calls += 1
        return -700


class ObjectSpy:
    str_calls = 0
    repr_calls = 0
    format_calls = 0
    int_calls = 0

    def __str__(self) -> str:
        self.str_calls += 1
        return SECRET_SERIAL

    def __repr__(self) -> str:
        self.repr_calls += 1
        return SECRET_SERIAL

    def __format__(self, format_spec: str) -> str:
        self.format_calls += 1
        return SECRET_SERIAL

    def __int__(self) -> int:
        self.int_calls += 1
        return errno.EIO


@pytest.mark.parametrize(
    ("number", "suffix"),
    [
        pytest.param(None, "", id="absent"),
        pytest.param(errno.EIO, " (errno 5 EIO)", id="known"),
        pytest.param(987654, " (errno 987654)", id="unknown"),
        pytest.param(-1, " (errno -1)", id="negative"),
        pytest.param(0, " (errno 0)", id="zero"),
        pytest.param(-(2**31), " (errno -2147483648)", id="c-int-min"),
        pytest.param(2**31 - 1, " (errno 2147483647)", id="c-int-max"),
        pytest.param(True, "", id="true-not-errno"),
        pytest.param(False, "", id="false-not-errno"),
        pytest.param("5 " + SECRET_SERIAL, "", id="string-not-errno"),
        pytest.param(5.0, "", id="float-not-errno"),
        pytest.param(ObjectSpy(), "", id="object-not-errno"),
        pytest.param(NumericSpy(errno.EIO), " (errno 5 EIO)", id="int-subclass"),
        pytest.param(2**31, "", id="above-c-int"),
        pytest.param(-(2**31) - 1, "", id="below-c-int"),
        pytest.param(10**5000, "", id="huge-no-string-conversion"),
        pytest.param(-(10**5000), "", id="huge-negative-no-string-conversion"),
        pytest.param(NumericSpy(2**31), "", id="int-subclass-above-c-int"),
    ],
)
def test_formatter_uses_only_class_and_trusted_bounded_errno(
    monkeypatch: pytest.MonkeyPatch,
    number: object,
    suffix: str,
) -> None:
    error = private_error()
    cause, context = error.__cause__, error.__context__
    monkeypatch.setattr(error, "errno", number)

    summary = capture.format_capture_error(error)

    assert summary == "RenderSpyOSError" + suffix
    assert_private(summary)
    assert error.errno is number
    assert error.__cause__ is cause and error.__context__ is context
    assert (error.str_calls, error.repr_calls) == (0, 0)
    if isinstance(number, (NumericSpy, ObjectSpy)):
        assert (number.str_calls, number.repr_calls, number.format_calls, number.int_calls) == (
            0,
            0,
            0,
            0,
        )


@pytest.mark.parametrize("permission", [False, True])
def test_output_error_constructor_keeps_controlled_library_text_and_safe_fields(
    permission: bool,
) -> None:
    output = Path("user-selected-port/capture.json")
    original = private_error(permission)
    error = capture_cli.CaptureOutputError(output, original)

    assert error.output is output
    assert error.error_summary == (
        "RenderSpyPermissionError (errno 13 EACCES)"
        if permission
        else "RenderSpyOSError (errno 5 EIO)"
    )
    assert str(error) == f"{output}: {type(original).__name__}"
    assert_private(str(error))
    assert (original.str_calls, original.repr_calls) == (0, 0)


class RenderSpyCaptureOutputError(capture_cli.CaptureOutputError):
    str_calls = 0
    repr_calls = 0

    def __str__(self) -> str:
        self.str_calls += 1
        return PAYLOAD

    def __repr__(self) -> str:
        self.repr_calls += 1
        return PAYLOAD


def test_main_output_error_subclass_does_not_trust_text_or_output_fields(
    boundary: CliBoundary,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = private_error()
    error = RenderSpyCaptureOutputError(Path(FILENAME), original)
    monkeypatch.setattr(error, "error_summary", PAYLOAD, raising=False)
    monkeypatch.setattr(error, "errno", errno.EIO)
    error.__cause__ = original
    inject_failure(boundary, monkeypatch, "discovery-first", error)

    assert capture_cli.main() == 2

    output = capsys.readouterr()
    assert output.out == ""
    assert "RenderSpyCaptureOutputError (errno 5 EIO)" in output.err
    assert_private(output.err)
    assert "do not run as root" not in output.err
    assert (error.str_calls, error.repr_calls) == (0, 0)
    assert (original.str_calls, original.repr_calls) == (0, 0)
    assert error.__cause__ is original
    assert [device.close_count for device in boundary.devices] == [0, 0]


def test_formatter_needs_no_exception_cause_or_context() -> None:
    original = private_error()
    original.__cause__ = original.__context__ = None

    summary = capture.format_capture_error(original)

    assert summary == "RenderSpyOSError (errno 5 EIO)"
    assert_private(summary)
    assert original.__cause__ is None and original.__context__ is None
    assert (original.str_calls, original.repr_calls) == (0, 0)


def test_main_exact_output_error_uses_fields_without_cause_or_rendering(
    boundary: CliBoundary,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "user-approved-port.json"
    original = private_error()
    original.__cause__ = original.__context__ = None
    wrapper = capture_cli.CaptureOutputError(output_path, original)
    wrapper_renders: list[str] = []

    def render(_error: capture_cli.CaptureOutputError) -> str:
        wrapper_renders.append("render")
        return PAYLOAD

    async def run(args: argparse.Namespace) -> int:
        assert args.output == output_path
        raise wrapper

    monkeypatch.setattr(capture_cli.CaptureOutputError, "__str__", render)
    monkeypatch.setattr(capture_cli.CaptureOutputError, "__repr__", render)
    monkeypatch.setattr(capture_cli, "run", run)
    monkeypatch.setattr(
        capture_cli.sys, "argv", ["naga-control-capture", "--output", str(output_path)]
    )

    assert capture_cli.main() == 2

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == f"Capture output error: {output_path}: RenderSpyOSError (errno 5 EIO)\n"
    assert_private(output.err)
    assert "do not run as root" not in output.err
    assert type(wrapper) is capture_cli.CaptureOutputError
    assert wrapper.output is output_path
    assert wrapper.error_summary == "RenderSpyOSError (errno 5 EIO)"
    assert wrapper.__cause__ is None and wrapper.__context__ is None
    assert original.__cause__ is None and original.__context__ is None
    assert wrapper_renders == []
    assert (original.str_calls, original.repr_calls) == (0, 0)
    assert boundary.calls == []
