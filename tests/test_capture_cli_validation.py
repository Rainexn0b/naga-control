"""Capture CLI parser contracts, including finite positive durations."""

from pathlib import Path

import pytest

from naga_control.diagnostics import capture_cli


@pytest.mark.parametrize("plate", ["2", "6", "12", "unknown"])
def test_parser_preserves_valid_options(tmp_path: Path, plate: str) -> None:
    output = tmp_path / "capture.json"
    args = capture_cli.build_parser().parse_args(
        [
            "--list",
            "--duration",
            "0.001",
            "--include-identifiers",
            "--openrazer-revision",
            "fake-revision",
            "--firmware",
            "v1",
            "--driver-mode",
            "3:0",
            "--plate",
            plate,
            "--output",
            str(output),
        ]
    )
    assert vars(args) == dict(
        list=True,
        duration=0.001,
        plate=plate,
        output=output,
        include_identifiers=True,
        openrazer_revision="fake-revision",
        firmware="v1",
        driver_mode="3:0",
    )


def test_invalid_plate_has_parser_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        capture_cli.build_parser().parse_args(["--plate", "3"])
    assert raised.value.code == 2
    assert "invalid choice: '3'" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["nan", "-nan", "inf", "-inf", "Infinity", "1e999"])
def test_nonfinite_duration_is_rejected(
    value: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        capture_cli.build_parser().parse_args([f"--duration={value}"])
    assert raised.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "--duration" in output.err and "finite" in output.err
