"""AppImage assembly failure diagnostics use fakes only, no real build."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.appimage_portable_fakes import INNER, read_text

FIXED_LOG = "/workspace/buildlog/naga-control/step-14-appimage.log"
BUILD_CMD = "/tmp/opencode/portable-venv/bin/python -m buildpython --run-steps AppImage"


def _extract_wrapper_block() -> str:
    text = read_text(INNER)
    assign = f'appimage_log="{FIXED_LOG}"'
    start = text.index(assign)
    marker = f"if {BUILD_CMD}; then"
    assert text.index(marker) > start
    anchor = '  fi\n  image="$(one_appimage)"'
    end = text.index(anchor, start) + len("  fi")
    return text[start:end]


def _run_extracted_wrapper(
    tmp_path: Path, *, build_exit: int, log_content: str | None
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    block = _extract_wrapper_block()
    case = tmp_path / f"case-{build_exit}-{'log' if log_content is not None else 'nolog'}"
    case.mkdir(parents=True, exist_ok=True)
    fake_build = case / "fake-build.sh"
    fake_build.write_text(f"#!/bin/bash\nexit {build_exit}\n", encoding="utf-8")
    fake_build.chmod(0o755)
    temp_log = case / "step-14-appimage.log"
    if log_content is not None:
        temp_log.write_text(log_content, encoding="utf-8")
    elif temp_log.exists():
        temp_log.unlink()
    marker = case / "downstream-marker"
    if marker.exists():
        marker.unlink()
    adapted = block.replace(FIXED_LOG, str(temp_log)).replace(BUILD_CMD, str(fake_build))
    harness = case / "harness.sh"
    harness.write_text(
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        f'marker="{marker}"\n'
        "under_test() {\n"
        f"{adapted}\n"
        "  printf 'downstream-reached\\n' >> \"$marker\"\n"
        "}\n"
        "under_test\n",
        encoding="utf-8",
    )
    harness.chmod(0o755)
    result = subprocess.run(
        ["/bin/bash", str(harness)],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    return result, temp_log, marker


def test_wrapper_uses_fixed_log_and_preserves_status() -> None:
    text = read_text(INNER)
    assert FIXED_LOG in text
    assert f"if {BUILD_CMD}; then" in text
    assert "status=$?" in text
    assert "step-14-appimage.log" in text
    assert "log missing" in text
    assert 'return "$status"' in text or 'exit "$status"' in text
    block = _extract_wrapper_block()
    assert "cat " in block
    assert block.index("status=$?") < block.index("cat ")
    assert block.index("cat ") < block.index('"$status"')
    build_pos = text.index(BUILD_CMD)
    downstream_pos = text.index('image="$(one_appimage)"')
    assert build_pos < downstream_pos
    assert "portable build complete; static gate pending" in text
    assert text.index('return "$status"') < downstream_pos


def test_failure_prints_log_and_preserves_status(tmp_path: Path) -> None:
    content = "fake-step-14-traceback: assembly boom\n"
    result, _, marker = _run_extracted_wrapper(tmp_path, build_exit=1, log_content=content)
    assert result.returncode == 1
    assert content.strip() in result.stdout
    assert not marker.exists()


def test_failure_preserves_nontrivial_status_without_cat_mask(tmp_path: Path) -> None:
    content = "fake-step-14-detail: linker line\n"
    result, _, marker = _run_extracted_wrapper(tmp_path, build_exit=7, log_content=content)
    assert result.returncode == 7
    assert content.strip() in result.stdout
    assert not marker.exists()


def test_failure_without_log_reports_missing_and_preserves_status(tmp_path: Path) -> None:
    result, temp_log, marker = _run_extracted_wrapper(tmp_path, build_exit=1, log_content=None)
    assert result.returncode == 1
    assert "log missing" in result.stderr
    assert str(temp_log) in result.stderr
    assert not marker.exists()


def test_success_prints_no_failure_log_and_reaches_downstream(tmp_path: Path) -> None:
    content = "fake-step-14-traceback: must stay silent on success\n"
    result, _, marker = _run_extracted_wrapper(tmp_path, build_exit=0, log_content=content)
    assert result.returncode == 0
    assert content.strip() not in result.stdout
    assert content.strip() not in result.stderr
    assert "log missing" not in result.stderr
    assert marker.exists()
