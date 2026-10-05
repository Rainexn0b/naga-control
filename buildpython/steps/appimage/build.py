from __future__ import annotations

import shlex
import shutil
import sys
import tomllib
from pathlib import Path

from ...utils.paths import repo_root
from ...utils.subproc import RunResult, run
from .assets import copy_assets
from .runtime import (
    RUNTIME_PROBE,
    copy_runtime,
    linked_libpython,
    native_arch,
    runtime_info,
    selected_python,
)
from .tool import download_appimagetool


def appimage_path() -> Path:
    root = repo_root()
    with (root / "pyproject.toml").open("rb") as source:
        version = tomllib.load(source)["project"]["version"]
    arch = native_arch()
    return root / "dist" / f"Naga-Control-{version}-{arch}.AppImage"


class _CommandFailed(Exception):
    def __init__(self, exit_code: int) -> None:
        self.exit_code = exit_code


def build_appimage() -> RunResult:
    """Assemble Naga's AppDir and return all subprocess output, including failures."""
    root = repo_root()
    commands: list[str] = []
    stdout: list[str] = []
    stderr: list[str] = []
    artifact: Path | None = None
    exit_code = 0

    def execute(args: list[str]) -> str:
        commands.append(shlex.join(args))
        result = run(
            args,
            cwd=str(root),
            env_overrides={"ARCH": native_arch(), "PYTHONNOUSERSITE": "1"},
        )
        stdout.append(result.stdout)
        stderr.append(result.stderr)
        if result.exit_code:
            raise _CommandFailed(result.exit_code)
        return result.stdout

    try:
        artifact = appimage_path()
        artifact.unlink(missing_ok=True)
        work = root / "build/appimage"
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True)
        appdir = work / "AppDir"
        info = runtime_info(
            execute([selected_python(), "-I", "-c", RUNTIME_PROBE]), arch=native_arch()
        )
        execute([sys.executable, "-I", "-m", "build", str(root), "--wheel", "--outdir", str(work)])
        wheels = list(work.glob("naga_control-*.whl"))
        if len(wheels) != 1:
            raise ValueError(f"Expected exactly one freshly built Naga wheel, found {len(wheels)}")
        venv = work / "venv"
        execute([str(info.executable), "-I", "-m", "venv", str(venv)])
        python = str(venv / "bin/python")
        execute([python, "-I", "-m", "pip", "install", "--upgrade", "pip"])
        execute(
            [python, "-I", "-m", "pip", "install", str(wheels[0]), "dbus-python", "numpy>=1.26,<3"]
        )
        library = linked_libpython(execute(["ldd", str(info.executable)]))
        copy_runtime(appdir=appdir, venv=venv, info=info, libpython=library)
        copy_assets(root=root, appdir=appdir)
        tool = download_appimagetool(work=work, arch=info.arch)
        artifact.parent.mkdir(parents=True, exist_ok=True)
        execute([str(tool), "--appimage-extract-and-run", str(appdir), str(artifact)])
        if not artifact.is_file() or artifact.stat().st_size == 0:
            raise ValueError(f"Expected nonempty AppImage was not produced: {artifact}")
        artifact.chmod(artifact.stat().st_mode | 0o111)
        stdout.append(f"Built AppImage: {artifact}\n")
    except _CommandFailed as exc:
        exit_code = exc.exit_code
    except Exception as exc:
        exit_code = 1
        stderr.append(f"AppImage assembly failed: {type(exc).__name__}: {exc}\n")
    if exit_code and artifact is not None:
        try:
            artifact.unlink(missing_ok=True)
        except OSError as exc:
            stderr.append(f"Could not remove failed AppImage: {exc}\n")
    return RunResult(
        "\n".join(commands) or "appimage-build", "".join(stdout), "".join(stderr), exit_code
    )


def appimage_build_runner() -> RunResult:
    return build_appimage()
