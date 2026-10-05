from __future__ import annotations

import os
import shlex
import shutil
import tomllib

from ...utils.paths import repo_root
from ...utils.subproc import RunResult, run
from .build import appimage_path


def smoke_script(artifact: str, version: str) -> str:
    return "\n".join(
        [
            "set -euo pipefail",
            "export DEBIAN_FRONTEND=noninteractive",
            "apt-get update -qq",
            "apt-get install -y --no-install-recommends "
            "libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3 libudev1 "
            "libglib2.0-0t64 >/dev/null",
            "useradd --create-home --uid 10001 naga-smoke",
            f"cp {shlex.quote('/dist/' + artifact)} /work/naga.AppImage",
            "chmod +x /work/naga.AppImage",
            "./naga.AppImage --appimage-extract >/dev/null",
            'export APPDIR="$PWD/squashfs-root"',
            "export QT_QPA_PLATFORM=offscreen",
            'APP=(runuser -u naga-smoke -- "$APPDIR/AppRun")',
            '"${APP[@]}" python -c '
            + shlex.quote(
                "import dbus, dbus_next, evdev, pyudev, tomli_w, packaging, numpy; "
                "from importlib.metadata import version; "
                f"assert version('naga-control') == {version!r}; print('runtime-imports-ok')"
            ),
            '"${APP[@]}" python -c "from PySide6.QtWidgets import QApplication; '
            "from naga_control.gui.app import main; "
            "app = QApplication([]); print('qt-offscreen-ok')\"",
            '"${APP[@]}" service --help',
            '"${APP[@]}" capture --help',
            '"${APP[@]}" integration --help',
            '"${APP[@]}" python -c '
            + shlex.quote(
                "from pathlib import Path; from tempfile import TemporaryDirectory; "
                "from naga_control.integration_cli import default_source_dir, install; "
                "from contextlib import ExitStack; "
                "stack = ExitStack(); "
                "temporary = Path(stack.enter_context(TemporaryDirectory())); "
                "installed = install(default_source_dir(), home=temporary / 'home', "
                "udev_dir=temporary / 'udev', exec_prefix=Path('/test/naga.AppImage')); "
                "assert len(installed) == 8; "
                "assert 'KillMode=mixed' in "
                "(temporary / 'home/.config/systemd/user/naga-control.service').read_text(); "
                "stack.close(); print('integration-payload-ok')"
            ),
            "printf '%s\\n' appimage-smoke-ok",
        ]
    )


def appimage_smoke_runner() -> RunResult:
    artifact = appimage_path()
    if not artifact.is_file():
        return RunResult("appimage-smoke", "", f"AppImage not found: {artifact}\n", 2)
    docker = shutil.which("docker")
    if docker is None:
        return RunResult("appimage-smoke", "", "Docker is required for AppImage smoke checks\n", 2)
    with (repo_root() / "pyproject.toml").open("rb") as source:
        version = tomllib.load(source)["project"]["version"]
    # No device mounts, session bus, GUI, or service startup: only imports and help.
    return run(
        [
            docker,
            "run",
            "--rm",
            "-v",
            f"{artifact.parent}:/dist:ro",
            "-w",
            "/work",
            os.environ.get("NAGA_APPIMAGE_SMOKE_IMAGE", "ubuntu:24.04"),
            "bash",
            "-lc",
            smoke_script(artifact.name, version),
        ],
        cwd=str(repo_root()),
    )
