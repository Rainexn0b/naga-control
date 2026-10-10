"""Smoke identity staging regressions (fakes only, no privileged execution).

Covers the 24.04 smoke permission root cause where root extracted the
AppImage under ``/work`` so ``runuser -u naga-smoke`` could not execute
``squashfs-root/AppRun``. The fix stages and extracts as the same
``naga-smoke`` uid inside a private ``0700`` workdir. These tests use only
structural assertions plus a controlled ``tmp_path`` fake-``PATH`` harness
that simulates ``0700`` staging/extraction modes and uid markers. They do
not run real ``apt``/``useradd``/``install``/``runuser``, do not assert
actual cross-uid host behavior, and do not start containers or touch
devices.
"""

from __future__ import annotations

import os
import shlex
import stat
import subprocess
from pathlib import Path

import pytest

from buildpython.steps.appimage import smoke

ARTIFACT = "Naga-Control-9.8.7-x86_64.AppImage"
VERSION = "9.8.7"
PRIVATE_WORK = "/home/naga-smoke/work"


def _script(
    artifact: str = ARTIFACT,
    version: str = VERSION,
) -> str:
    return smoke.smoke_script(artifact, version)


def _lines(script: str) -> list[str]:
    return script.splitlines()


def _index_containing(lines: list[str], needle: str) -> int:
    for index, line in enumerate(lines):
        if needle in line:
            return index
    raise AssertionError(f"missing line containing: {needle!r}")


def _has_root_extract(script: str) -> bool:
    """True when any extract line runs without the same-uid runuser prefix."""
    for line in script.splitlines():
        if "--appimage-extract" in line and "runuser -u naga-smoke" not in line:
            return True
    return False


def test_script_passes_bash_syntax_check() -> None:
    script = _script()
    result = subprocess.run(
        ["bash", "-n"], input=script, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_private_owned_staging_before_same_uid_extract() -> None:
    script = _script()
    lines = _lines(script)
    assert "useradd --create-home --uid 10001 naga-smoke" in script
    mkdir_line = next(line for line in lines if "install -d" in line)
    assert "-o naga-smoke" in mkdir_line and "-g naga-smoke" in mkdir_line
    assert "0700" in mkdir_line and PRIVATE_WORK in mkdir_line
    expected_copy = (
        f"install -m 0700 -o naga-smoke -g naga-smoke "
        f"{shlex.quote('/dist/' + ARTIFACT)} {PRIVATE_WORK}/naga.AppImage"
    )
    assert expected_copy in script
    assert f"cd {PRIVATE_WORK}" in script
    extract = "runuser -u naga-smoke -- ./naga.AppImage --appimage-extract >/dev/null"
    assert extract in script
    assert not _has_root_extract(script)
    order = [
        "useradd --create-home --uid 10001 naga-smoke",
        "install -d",
        f"{PRIVATE_WORK}/naga.AppImage",
        f"cd {PRIVATE_WORK}",
        "./naga.AppImage --appimage-extract",
        'export APPDIR="$PWD/squashfs-root"',
        'APP=(runuser -u naga-smoke -- "$APPDIR/AppRun")',
        '"${APP[@]}" python -c',
    ]
    positions = [_index_containing(lines, needle) for needle in order]
    assert positions == sorted(positions), positions
    first_app = next(i for i, line in enumerate(lines) if '"${APP[@]}"' in line)
    assert _index_containing(lines, "./naga.AppImage --appimage-extract") < first_app


def test_no_root_staging_or_world_widening() -> None:
    script = _script()
    lines = _lines(script)
    assert not any(line.startswith("cp ") for line in lines)
    assert "chmod +x /work/naga.AppImage" not in script
    for forbidden in (
        "chmod -R",
        "chown -R",
        "chown ",
        "chmod 0777",
        "chmod 777",
        "0777",
        " /work/naga.AppImage",
        "chmod +x /work",
        " --appimage-extract-and-run",
    ):
        assert forbidden not in script, forbidden
    # The pre-fix shape extracted as root and must fail this file's gate.
    old_bad = "\n".join(
        [
            "set -euo pipefail",
            "useradd --create-home --uid 10001 naga-smoke",
            f"cp {shlex.quote('/dist/' + ARTIFACT)} /work/naga.AppImage",
            "chmod +x /work/naga.AppImage",
            "./naga.AppImage --appimage-extract >/dev/null",
            'export APPDIR="$PWD/squashfs-root"',
            'APP=(runuser -u naga-smoke -- "$APPDIR/AppRun")',
        ]
    )
    assert _has_root_extract(old_bad)
    assert "install -d -m" not in old_bad or PRIVATE_WORK not in old_bad


def test_runtime_contract_preserved_without_live_execution() -> None:
    script = _script()
    assert "QT_QPA_PLATFORM=offscreen" in script
    assert 'runuser -u naga-smoke -- "$APPDIR/AppRun"' in script
    assert "from PySide6.QtWidgets import QApplication" in script
    assert "from naga_control.gui.app import main" in script
    # GUI module is imported for offscreen construction only; main is not run.
    assert "main()" not in script and "app.exec" not in script
    assert '"${APP[@]}" service --help' in script
    assert '"${APP[@]}" capture --help' in script
    assert '"${APP[@]}" integration --help' in script
    assert "integration-payload-ok" in script
    assert "TemporaryDirectory" in script
    assert "default_source_dir" in script
    assert "version(" in script and VERSION in script
    assert "naga-control" in script
    assert VERSION in script
    for forbidden in (
        "service --debug",
        "EVIOCGRAB",
        "/dev/uinput",
        "/dev/input",
        "--install",
        "main.launch",
    ):
        assert forbidden not in script, forbidden
    module_text = Path(smoke.__file__).read_text(encoding="utf-8")
    assert "ubuntu:24.04" in module_text


def test_artifact_path_uses_existing_quote_escaping() -> None:
    hostile = "Naga Control-1;evil.AppImage"
    script = _script(artifact=hostile)
    assert shlex.quote("/dist/" + hostile) in script
    assert "/dist/" + hostile not in script.replace(shlex.quote("/dist/" + hostile), "")


def test_runner_keeps_readonly_dist_mount(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    artifact = dist / ARTIFACT
    artifact.write_bytes(b"fake-image-bytes")
    monkeypatch.setattr(smoke, "appimage_path", lambda: artifact)

    def _which(_name: str) -> str | None:
        return "/usr/bin/docker"

    monkeypatch.setattr(smoke.shutil, "which", _which)
    captured: dict[str, list[str]] = {}

    def fake_run(args: list[str], *, cwd: str) -> object:
        captured["args"] = args
        captured["cwd"] = [cwd]
        from buildpython.utils.subproc import RunResult

        return RunResult("appimage-smoke", "", "", 0)

    monkeypatch.setattr(smoke, "run", fake_run)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "9.8.7"\n')
    monkeypatch.setattr(smoke, "repo_root", lambda: tmp_path)
    assert smoke.appimage_smoke_runner().exit_code == 0
    args = captured["args"]
    assert f"{dist}:/dist:ro" in args
    assert "-w" in args and "/work" in args
    assert "ubuntu:24.04" in args
    raw: object = args[-1]
    assert isinstance(raw, str)
    script: str = raw
    assert "/dist:ro" not in script
    assert ">/dist" not in script and " /dist/" not in script.replace(
        shlex.quote("/dist/" + ARTIFACT), ""
    )
    assert artifact.read_bytes() == b"fake-image-bytes"


def test_fake_staging_modes_order_and_source_unchanged(tmp_path: Path) -> None:
    """Simulated 0700 staging/extract with logging fakes in tmp only.

    Limit: measures fake file modes and log order in ``tmp_path``; does not
    prove real cross-uid ``runuser`` execution on a host or in CI.
    """

    script = _script()
    assert "0700" in script
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    log = tmp_path / "calls.log"
    log.write_text("", encoding="utf-8")
    work = tmp_path / "work"
    source = tmp_path / "dist" / ARTIFACT
    source.parent.mkdir(parents=True)
    source.write_bytes(b"fake-image-bytes")
    source.chmod(0o600)
    before = source.read_bytes()
    (fakebin / "install").write_text(
        "#!/bin/sh\n"
        f'echo "install $*" >> {shlex.quote(str(log))}\n'
        'dest=""; for a in "$@"; do dest="$a"; done\n'
        'if [ "$1" = "-d" ]; then\n'
        '  mkdir -p "$dest"; chmod 0700 "$dest"\n'
        "else\n"
        '  mkdir -p "$(dirname "$dest")"; printf staged > "$dest"; chmod 0700 "$dest"\n'
        "fi\n",
        encoding="utf-8",
    )
    (fakebin / "runuser").write_text(
        "#!/bin/sh\n"
        f'echo "runuser $*" >> {shlex.quote(str(log))}\n'
        'if printf "%s" "$*" | grep -q "appimage-extract"; then\n'
        "  mkdir -p squashfs-root; chmod 0700 squashfs-root\n"
        '  printf "naga-smoke:10001" > squashfs-root/.fake-uid\n'
        "fi\n",
        encoding="utf-8",
    )
    for name in ("install", "runuser"):
        (fakebin / name).chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = str(fakebin) + os.pathsep + "/usr/bin" + os.pathsep + "/bin"
    staged = work / "naga.AppImage"
    commands = (
        f"install -d -m 0700 -o naga-smoke -g naga-smoke {shlex.quote(str(work))}\n"
        f"install -m 0700 -o naga-smoke -g naga-smoke "
        f"{shlex.quote(str(source))} {shlex.quote(str(staged))}\n"
        f"cd {shlex.quote(str(work))}\n"
        "runuser -u naga-smoke -- ./naga.AppImage --appimage-extract >/dev/null\n"
    )
    result = subprocess.run(
        ["bash", "-e", "-c", commands],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(work.stat().st_mode) == 0o700
    assert stat.S_IMODE(staged.stat().st_mode) == 0o700
    extracted = work / "squashfs-root"
    assert stat.S_IMODE(extracted.stat().st_mode) == 0o700
    assert (extracted / ".fake-uid").read_text(encoding="utf-8") == "naga-smoke:10001"
    # Root-producer source stays byte-identical and read-protected; no widening.
    assert source.read_bytes() == before
    assert stat.S_IMODE(source.stat().st_mode) == 0o600
    logged = log.read_text(encoding="utf-8")
    assert logged.index("install -d -m 0700") < logged.index("install -m 0700")
    assert logged.index("install -m 0700") < logged.index(
        "runuser -u naga-smoke -- ./naga.AppImage"
    )
    assert "0777" not in logged and "777" not in logged.replace("0700", "")
    # A failing preparation step still propagates under set -e.
    failing = "set -e\nfalse\nprintf reached\n"
    failed = subprocess.run(
        ["bash", "-e", "-c", failing],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert failed.returncode != 0
    assert "reached" not in failed.stdout
