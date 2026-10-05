"""Build orchestration contracts without real packaging or hardware."""

# pyright: reportPrivateUsage=false

import os
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from buildpython.core import cli, runner
from buildpython.core.model import Step
from buildpython.core.profiles import PROFILES
from buildpython.steps import step_defs
from buildpython.steps.appimage import build, smoke
from buildpython.utils.subproc import RunResult


def test_profiles_reference_registered_steps() -> None:
    names = {step.name for step in step_defs.steps()}
    for profile in PROFILES.values():
        assert set(profile.include_steps) <= names
    for profile in ("ci", "full", "release"):
        assert {"Ruff", "Ruff Format", "Type Check", "Pytest"} <= set(
            PROFILES[profile].include_steps
        )
    assert "AppImage" not in PROFILES["full"].include_steps
    assert PROFILES["release"].include_steps[-2:] == ["AppImage", "AppImage Smoke"]


def test_selectors_support_names_numbers_skips_and_deduplication() -> None:
    selected = cli._select_steps(["Ruff", "3", "Type Check"], ["13"], None)
    assert [step.name for step in selected] == ["Ruff"]
    with pytest.raises(SystemExit, match="Unknown step"):
        cli._select_steps(["unknown"], None, None)


def test_appimage_option_appends_build_and_smoke_once() -> None:
    selected = cli._select_steps(None, None, "quick")
    selected = cli._maybe_add_appimage(selected, enabled=True)
    assert cli._maybe_add_appimage(selected, enabled=True) == selected
    assert [step.name for step in selected][-2:] == ["AppImage", "AppImage Smoke"]


@pytest.mark.parametrize("name", ["Ruff", "Ruff Format", "Type Check"])
def test_missing_required_tools_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    def unavailable(module: str) -> bool:
        return False

    monkeypatch.setattr(runner, "_is_module_available", unavailable)

    def never_run() -> RunResult:
        raise AssertionError("Unavailable check executed")

    step = Step(1, name, "required tool", tmp_path / "step.log", never_run)
    outcome = runner.run_step(
        step,
        index=1,
        total_steps=1,
        name_width=12,
        label_width=5,
        verbose=False,
        compact_output=True,
    )
    assert outcome.status == "failure"
    assert outcome.exit_code != 0
    assert "not installed" in step.log_file.read_text()


def test_runner_records_failure_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "buildlog_dir", lambda: tmp_path)

    def fail() -> RunResult:
        raise RuntimeError("synthetic runner failure")

    steps = [
        Step(1, "Synthetic Failure", "fake", tmp_path / "failure.log", fail),
        Step(
            2, "Synthetic Pass", "fake", tmp_path / "pass.log", lambda: RunResult("fake", "", "", 0)
        ),
    ]
    assert runner.run(steps, verbose=False, continue_on_error=True) != 0
    assert "synthetic runner failure" in (tmp_path / "failure.log").read_text()
    assert (tmp_path / "pass.log").is_file()
    assert '"status": "failure"' in (tmp_path / "build-summary.json").read_text()


def test_appimage_uses_python_builder_and_exact_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "9.8.7"\n')
    monkeypatch.setattr(build, "repo_root", lambda: tmp_path)
    monkeypatch.setenv("ARCH", "x86_64")
    artifact = build.appimage_path()
    assert artifact.name == "Naga-Control-9.8.7-x86_64.AppImage"

    result = RunResult("fake Python build", "", "", 0)

    monkeypatch.setattr(build, "build_appimage", lambda: result)
    assert build.appimage_build_runner() is result


def test_smoke_requires_artifact_and_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = tmp_path / "Naga-Control-9.8.7-x86_64.AppImage"
    monkeypatch.setattr(smoke, "appimage_path", lambda: artifact)
    assert smoke.appimage_smoke_runner().exit_code != 0
    artifact.touch()

    def unavailable(name: str) -> None:
        return None

    monkeypatch.setattr(smoke.shutil, "which", unavailable)
    result = smoke.appimage_smoke_runner()
    assert result.exit_code != 0
    assert "Docker" in result.stderr


def test_smoke_script_is_valid_and_only_runs_help_or_offscreen_imports() -> None:
    script = smoke.smoke_script("Naga-Control-9.8.7-x86_64.AppImage", "9.8.7")
    result = subprocess.run(
        ["bash", "-n"], input=script, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "9.8.7" in script
    assert "QT_QPA_PLATFORM=offscreen" in script
    assert '"${APP[@]}" service --help' in script
    assert '"${APP[@]}" capture --help' in script
    assert '"${APP[@]}" integration --help' in script
    assert 'runuser -u naga-smoke -- "$APPDIR/AppRun"' in script
    assert "integration-payload-ok" in script
    assert "TemporaryDirectory" in script
    assert "default_source_dir" in script
    assert "--install" not in script
    assert "/dev/input" not in script


@pytest.mark.parametrize("launches", [1, 4])
def test_apprun_bridges_only_the_host_openrazer_package(tmp_path: Path, launches: int) -> None:
    host_site = tmp_path / "host-site"
    package = host_site / "openrazer"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    daemon = host_site / "openrazer_daemon"
    daemon.mkdir()
    (daemon / "__init__.py").write_text("", encoding="utf-8")
    appdir = tmp_path / "AppDir"
    bin_dir = appdir / "usr/bin"
    bin_dir.mkdir(parents=True)
    (appdir / "usr/lib/python3.12").mkdir(parents=True)
    # Substitute the host interpreter, but execute AppRun's actual discovery code.
    host_env = bin_dir / "env"
    host_env.write_text(
        "#!/usr/bin/env bash\n"
        'while [ "$1" = -u ]; do unset "$2"; shift 2; done\n'
        "shift\n"
        f"exec {shlex.quote(sys.executable)} -c "
        f'"import sys; sys.path.insert(0, {str(host_site)!r}); $2" "$3"\n',
        encoding="utf-8",
    )
    host_env.chmod(0o755)
    bundled_python = bin_dir / "python3"
    bundled_python.write_text(
        "#!/usr/bin/env bash\nunset PYTHONHOME LD_LIBRARY_PATH\n"
        f"exec {shlex.quote(sys.executable)} -c "
        + shlex.quote(
            "import os, sys; assert sys.flags.no_user_site; assert sys.flags.safe_path; "
            f"assert os.readlink(os.environ['PYTHONPATH'] + '/openrazer_daemon') == {str(daemon)!r}; "
            "print(os.readlink(os.environ['PYTHONPATH'] + '/openrazer'))"
        )
        + "\n",
        encoding="utf-8",
    )
    bundled_python.chmod(0o755)
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(tmp_path / "host-shadow")
    environment.update(
        APPDIR=str(appdir), HOME=str(tmp_path), XDG_CACHE_HOME=str(tmp_path / "cache")
    )
    apprun = Path(__file__).resolve().parents[1] / "buildpython/steps/appimage/AppRun"

    def launch(index: int) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(apprun), "python"],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    with ThreadPoolExecutor(max_workers=launches) as executor:
        results = list(executor.map(launch, range(launches)))
    for result in results:
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""
        assert Path(result.stdout.strip()) == package
