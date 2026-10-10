"""Guard the small workflow graph without an undeclared YAML parser dependency."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from tests.release_assets_fakes import ROOT

WORKFLOW = (ROOT / ".github/workflows/release.yml").read_text()

PYTEST_LOG = "buildlog/naga-control/step-02-pytest.log"
SMOKE_LOG = "buildlog/naga-control/step-15-appimage-smoke.log"


def jobs() -> dict[str, str]:
    starts = list(re.finditer(r"^  ([a-z]+):$", WORKFLOW.split("jobs:\n", 1)[1], re.MULTILINE))
    body = WORKFLOW.split("jobs:\n", 1)[1]
    return {
        match[1]: body[
            match.end() : starts[index + 1].start() if index + 1 < len(starts) else len(body)
        ]
        for index, match in enumerate(starts)
    }


def test_metadata_blocks_both_read_only_independent_builds() -> None:
    graph = jobs()
    assert set(graph) == {"metadata", "appimage", "openrazer", "publish"}
    assert "permissions:\n  contents: read" in WORKFLOW
    for name in ("appimage", "openrazer"):
        assert "    needs: metadata\n" in graph[name]
        assert "contents: write" not in graph[name]
        assert "GH_TOKEN" not in graph[name]
        assert "gh release" not in graph[name]
        assert "actions/upload-artifact@v4" in graph[name]
    assert 'if [ "$GITHUB_EVENT_NAME" = push ]; then' in graph["metadata"]
    assert 'scripts/prepare_release.py "$GITHUB_REF_NAME"' in graph["metadata"]
    assert "--validation-only" in graph["metadata"]


def test_single_publisher_requires_both_successful_builds_and_only_tag_push() -> None:
    graph = jobs()
    publisher = graph["publish"]
    assert "needs: [metadata, appimage, openrazer]" in publisher
    assert "if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')" in publisher
    assert "always()" not in WORKFLOW
    assert WORKFLOW.count("contents: write") == 1
    assert WORKFLOW.count("GH_TOKEN:") == 1
    assert "pattern: '*-release-assets'" in publisher
    assert publisher.index("scripts/validate_release_assets.py") < publisher.index("GH_TOKEN:")
    assert "scripts/publish_release_assets.py" in publisher
    for forbidden in ("pytest", "makepkg", "buildpython --profile", '-e ".[dev]"'):
        assert forbidden not in publisher


def test_all_checkouts_disable_persisted_credentials() -> None:
    assert WORKFLOW.count("actions/checkout@v4") == 4
    assert WORKFLOW.count("persist-credentials: false") == 4


def test_appimage_test_gate_provides_fixture_archive_reader() -> None:
    assert "libarchive-tools" in jobs()["appimage"]


def test_standard_ci_provides_fixture_archive_reader_and_installer_lock() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "libarchive-tools" in workflow
    assert "util-linux" in workflow


def test_arch_prerequisites_and_unprivileged_build_without_sudoers() -> None:
    package = jobs()["openrazer"]
    assert "run: python buildpython/openrazer_packages/pin.py" in package
    assert "source buildpython/openrazer_packages/pin.conf" not in package
    assert "sudoers" not in package
    assert "NOPASSWD" not in package
    assert "github-cli" not in package
    for dependency in (
        "clang",
        "llvm",
        "lld",
        "linux-headers",
        "linux-lts-headers",
        "python-setuptools",
        "python-daemonize",
        "python-pyudev",
        "python-setproctitle",
        "python-gobject",
        "dbus-python",
        "xautomation",
        "python-numpy",
    ):
        assert dependency in package
    assert "runuser -u builduser -- makepkg --verifysource" in package
    assert "runuser -u builduser -- makepkg --cleanbuild --log" in package
    assert "--packages-only --create-checksums --check-imports" in package
    assert 'make KERNELDIR="$header" LLVM=1 driver' in package
    assert 'make KERNELDIR="$header" driver' in package
    assert "modprobe" not in package


def test_appimage_validates_source_then_controlled_builder_then_smoke() -> None:
    appimage = jobs()["appimage"]
    assert ".venv/bin/python -m buildpython --profile full" in appimage
    assert "--profile release" not in appimage
    assert "buildpython/steps/appimage/portable-build.sh" in appimage
    assert '.venv/bin/python -m buildpython --run-steps "AppImage Smoke"' in appimage
    full_pos = appimage.index("--profile full")
    portable_pos = appimage.index("portable-build.sh")
    smoke_pos = appimage.index('--run-steps "AppImage Smoke"')
    stage_pos = appimage.index("Stage exactly one AppImage")
    assert full_pos < portable_pos < smoke_pos < stage_pos


def test_static_gate_precedes_any_bundled_execution_or_staging() -> None:
    appimage = jobs()["appimage"]
    assert "RELEASE_VERSION: ${{ needs.metadata.outputs.version }}" in appimage
    assert appimage.index("RELEASE_VERSION") < appimage.index("portable-build.sh")
    assert "build/appimage/AppDir/usr/bin/python3" not in appimage
    assert 'PYTHONHOME="$PWD/build/appimage' not in appimage
    assert "dist/Naga-Control-*-x86_64.AppImage" in appimage
    assert 'test "${#images[@]}" = 1' in appimage


def test_controlled_timeout_is_bounded_and_assets_unchanged() -> None:
    appimage = jobs()["appimage"]
    assert "timeout-minutes: 60" in appimage
    assert "timeout-minutes: 30" not in appimage
    assert WORKFLOW.count("actions/upload-artifact@v4") == 3
    assert "name: appimage-release-assets" in WORKFLOW
    assert "name: openrazer-release-assets" in WORKFLOW
    assert "name: release-metadata" in WORKFLOW
    assert "workflow_dispatch" in WORKFLOW
    assert "if: github.event_name == 'push'" in jobs()["publish"]


def _validation_script(workflow_text: str, step_name: str) -> str:
    step_pos = workflow_text.index(f"- name: {step_name}")
    run_pos = workflow_text.index("run: |", step_pos)
    script_start = workflow_text.index("\n", run_pos) + 1
    next_step = workflow_text.find("\n      - ", script_start)
    block = workflow_text[script_start : next_step if next_step != -1 else len(workflow_text)]
    lines: list[str] = []
    for line in block.splitlines():
        if line.startswith("          "):
            lines.append(line[10:])
        elif not line.strip():
            lines.append("")
        else:
            break
    return "\n".join(lines) + "\n"


def test_release_validation_prints_pytest_log_and_preserves_status() -> None:
    appimage = jobs()["appimage"]
    assert ".venv/bin/python -m buildpython --profile full" in appimage
    assert PYTEST_LOG in appimage
    assert f"cat {PYTEST_LOG}" in appimage
    assert "status=$?" in appimage
    assert 'exit "$status"' in appimage
    assert 'if [ "$status" -ne 0 ]' in appimage
    assert "continue-on-error" not in appimage
    full_pos = appimage.index("--profile full")
    log_pos = appimage.index(PYTEST_LOG)
    portable_pos = appimage.index("portable-build.sh")
    smoke_pos = appimage.index('--run-steps "AppImage Smoke"')
    stage_pos = appimage.index("Stage exactly one AppImage")
    assert full_pos < log_pos < portable_pos < smoke_pos < stage_pos
    script = _validation_script(WORKFLOW, "Validate source with full profile on host")
    assert f"cat {PYTEST_LOG}" in script
    assert 'exit "$status"' in script
    result = subprocess.run(
        ["bash", "-n"], input=script, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_ci_validation_prints_pytest_log_and_preserves_status() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    assert ".venv/bin/python -m buildpython --profile ci" in workflow
    assert PYTEST_LOG in workflow
    assert f"cat {PYTEST_LOG}" in workflow
    assert "status=$?" in workflow
    assert 'exit "$status"' in workflow
    assert 'if [ "$status" -ne 0 ]' in workflow
    assert "continue-on-error" not in workflow
    script = _validation_script(workflow, "Standard validation (hardware tests remain excluded)")
    assert f"cat {PYTEST_LOG}" in script
    assert 'exit "$status"' in script
    result = subprocess.run(
        ["bash", "-n"], input=script, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr


def _write_fake_python(root: Path, exit_code: int, sentinel: str) -> None:
    python_path = root / ".venv/bin/python"
    python_path.parent.mkdir(parents=True, exist_ok=True)
    python_path.write_text(f"#!/bin/sh\necho '{sentinel}'\nexit {exit_code}\n", encoding="utf-8")
    python_path.chmod(0o755)


def test_appimage_smoke_wrapper_prints_smoke_log_and_preserves_status(tmp_path: Path) -> None:
    appimage = jobs()["appimage"]
    assert '.venv/bin/python -m buildpython --run-steps "AppImage Smoke"' in appimage
    assert SMOKE_LOG in appimage
    assert f"cat {SMOKE_LOG}" in appimage
    assert "continue-on-error" not in appimage
    assert "always()" not in appimage
    portable_pos = appimage.index("portable-build.sh")
    smoke_pos = appimage.index('--run-steps "AppImage Smoke"')
    log_pos = appimage.index(SMOKE_LOG)
    stage_pos = appimage.index("Stage exactly one AppImage")
    assert portable_pos < smoke_pos < log_pos < stage_pos
    script = _validation_script(WORKFLOW, "AppImage smoke on host container (Ubuntu 24.04)")
    assert script.splitlines()[0] == "set +e"
    assert '.venv/bin/python -m buildpython --run-steps "AppImage Smoke"' in script
    assert "status=$?" in script
    assert 'if [ "$status" -ne 0 ]' in script
    assert f"cat {SMOKE_LOG}" in script
    assert "missing" in script
    assert ">&2" in script
    assert 'exit "$status"' in script
    result = subprocess.run(
        ["bash", "-n"], input=script, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr
    marker = "smoke-log-marker-present"
    log_path = tmp_path / SMOKE_LOG
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(marker + "\n", encoding="utf-8")
    _write_fake_python(tmp_path, 13, "fake-python-sentinel-failure")
    run_result = subprocess.run(
        ["bash", "-e", "-c", script],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert run_result.returncode == 13
    assert marker in run_result.stdout
    assert "fake-python-sentinel-failure" in run_result.stdout


def test_appimage_smoke_wrapper_reports_missing_log(tmp_path: Path) -> None:
    script = _validation_script(WORKFLOW, "AppImage smoke on host container (Ubuntu 24.04)")
    _write_fake_python(tmp_path, 13, "fake-python-sentinel-missing")
    run_result = subprocess.run(
        ["bash", "-e", "-c", script],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert run_result.returncode == 13
    assert "fake-python-sentinel-missing" in run_result.stdout
    assert "missing" in run_result.stderr
    assert SMOKE_LOG in run_result.stderr


def test_appimage_smoke_wrapper_success_is_silent(tmp_path: Path) -> None:
    script = _validation_script(WORKFLOW, "AppImage smoke on host container (Ubuntu 24.04)")
    marker = "smoke-log-marker-silent"
    log_path = tmp_path / SMOKE_LOG
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(marker + "\n", encoding="utf-8")
    _write_fake_python(tmp_path, 0, "fake-python-sentinel-success")
    run_result = subprocess.run(
        ["bash", "-e", "-c", script],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert run_result.returncode == 0
    assert "fake-python-sentinel-success" in run_result.stdout
    assert marker not in run_result.stdout
    assert marker not in run_result.stderr
    assert "missing" not in run_result.stderr


def test_appimage_smoke_wrapper_preserves_status_when_cat_fails(tmp_path: Path) -> None:
    script = _validation_script(WORKFLOW, "AppImage smoke on host container (Ubuntu 24.04)")
    log_path = tmp_path / SMOKE_LOG
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("smoke-log-marker-cat\n", encoding="utf-8")
    _write_fake_python(tmp_path, 13, "fake-python-sentinel-cat")
    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    fake_cat = fake_bin / "cat"
    fake_cat.write_text("#!/bin/sh\necho fake-cat-failure >&2\nexit 7\n", encoding="utf-8")
    fake_cat.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
    run_result = subprocess.run(
        ["bash", "-e", "-c", script],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert run_result.returncode == 13
    assert "fake-cat-failure" in run_result.stderr
