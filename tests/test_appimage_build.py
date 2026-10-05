"""AppDir assembly contracts using only small temporary files and fake commands."""

import io
import json
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from buildpython.steps.appimage import assets, build, runtime, tool
from buildpython.utils.subproc import RunResult


def write(path: Path, content: str = "fixture") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def asset_sources(root: Path) -> None:
    for relative in assets.SYSTEM_TEMPLATES:
        write(root / "system" / relative, relative)
    for size in assets.ICON_SIZES:
        write(root / f"assets/icons/hicolor/{size}x{size}/apps/{assets.APP_ID}.png", str(size))
    write(root / f"assets/{assets.APP_ID}.svg", "svg")
    write(root / "buildpython/steps/appimage/AppRun", "#!/bin/sh\n")
    write(root / "buildpython/steps/appimage/probe-shutdown.py")
    write(root / "system/desktop/build.py")
    write(root / "assets/icons/hicolor/unwanted.txt")


def probe_data(root: Path) -> dict[str, object]:
    return {
        "implementation": "cpython",
        "platform": "linux",
        "arch": "x86_64",
        "bits": 64,
        "version": [3, 12],
        "full_version": "3.12.0",
        "executable": str(root / "base/bin/python3"),
        "stdlib": str(root / "base/lib/python3.12"),
        "dynload": str(root / "base/lib/python3.12/lib-dynload"),
        "platlibdir": "lib",
        "gil_disabled": False,
    }


@dataclass
class FakeAssembly:
    root: Path
    calls: list[list[str]] = field(default_factory=list[list[str]])
    failure: str = ""
    produce_artifact: bool = True
    produce_wheel: bool = True
    empty_artifact: bool = False

    def run(self, args: list[str], *, cwd: str, env_overrides: dict[str, str]) -> RunResult:
        assert cwd == str(self.root)
        assert env_overrides == {"ARCH": "x86_64", "PYTHONNOUSERSITE": "1"}
        self.calls.append(args)
        label = "probe" if "-c" in args else args[args.index("-m") + 1] if "-m" in args else args[0]
        if self.failure == label:
            if "--appimage-extract-and-run" in args:
                write(Path(args[-1]), "partial image")
            return RunResult(shlex.join(args), "complete failing stdout\n", "complete stderr\n", 23)
        stdout = f"{label} stdout\n"
        if label == "probe":
            stdout = json.dumps(probe_data(self.root))
        elif label == "build" and self.produce_wheel:
            write(self.root / "build/appimage/naga_control-9.8.7-py3-none-any.whl")
        elif label == "venv":
            write(Path(args[-1]) / "lib/python3.12/site-packages/PySide6/__init__.py", "bundled Qt")
            write(Path(args[-1]) / "lib/python3.12/site-packages/dbus/__init__.py", "bundled dbus")
        elif label == "ldd":
            stdout = f"libpython3.12.so.1.0 => {self.root}/base/lib/libpython3.12.so.1.0 (0x123)\n"
        elif "--appimage-extract-and-run" in args and self.produce_artifact:
            write(Path(args[-1]), "" if self.empty_artifact else "new image")
        return RunResult(shlex.join(args), stdout, f"{label} stderr\n", 0)

    def download(self, *, work: Path, arch: str) -> Path:
        assert work == self.root / "build/appimage"
        assert arch == "x86_64"
        return write(work / "appimagetool", "tool")


@pytest.fixture
def assembly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeAssembly:
    monkeypatch.setattr(build, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(runtime.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(runtime.platform, "system", lambda: "Linux")
    for variable in ("ARCH", "PYVER", "PYTHON_VERSION", "PYTHON_BIN"):
        monkeypatch.delenv(variable, raising=False)
    write(tmp_path / "pyproject.toml", '[project]\nversion = "9.8.7"\n')
    asset_sources(tmp_path)
    write(tmp_path / "base/bin/python3", "base interpreter")
    write(tmp_path / "base/lib/python3.12/os.py", "stdlib")
    write(tmp_path / "base/lib/python3.12/lib-dynload/_test.so", "extension")
    write(tmp_path / "base/lib/libpython3.12.so.1.0", "linked library")
    fake = FakeAssembly(tmp_path)
    monkeypatch.setattr(build, "run", fake.run)
    monkeypatch.setattr(build, "download_appimagetool", fake.download)
    return fake


def test_build_commands_use_selected_base_runtime_and_invoking_wheel_python(
    assembly: FakeAssembly, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTHON_BIN", "/selected/venv/bin/python")
    result = build.appimage_build_runner()
    assert result.exit_code == 0, result.stderr
    calls = assembly.calls
    root = assembly.root
    work = root / "build/appimage"
    assert calls[0] == ["/selected/venv/bin/python", "-I", "-c", runtime.RUNTIME_PROBE]
    assert calls[1] == [
        sys.executable,
        "-I",
        "-m",
        "build",
        str(root),
        "--wheel",
        "--outdir",
        str(work),
    ]
    assert calls[2] == [str(root / "base/bin/python3"), "-I", "-m", "venv", str(work / "venv")]
    assert calls[3] == [
        str(work / "venv/bin/python"),
        "-I",
        "-m",
        "pip",
        "install",
        "--upgrade",
        "pip",
    ]
    assert calls[4] == [
        str(work / "venv/bin/python"),
        "-I",
        "-m",
        "pip",
        "install",
        str(work / "naga_control-9.8.7-py3-none-any.whl"),
        "dbus-python",
        "numpy>=1.26,<3",
    ]
    assert calls[5] == ["ldd", str(root / "base/bin/python3")]
    assert calls[6] == [
        str(work / "appimagetool"),
        "--appimage-extract-and-run",
        str(work / "AppDir"),
        str(build.appimage_path()),
    ]
    assert "pip stdout" in result.stdout and "pip stderr" in result.stderr
    assert build.appimage_path().read_text() == "new image"
    assert build.appimage_path().stat().st_mode & 0o111
    appdir = work / "AppDir"
    assert (appdir / "usr/bin/python3").read_text() == "base interpreter"
    assert (appdir / "usr/lib/libpython3.12.so.1.0").read_text() == "linked library"
    assert (appdir / "usr/lib/python3.12/site-packages/dbus/__init__.py").is_file()


def test_default_runtime_selection_uses_invoking_python(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PYTHON_BIN", raising=False)
    assert runtime.selected_python() == sys.executable


def test_runtime_excludes_all_host_sites_and_retains_staged_dependencies(tmp_path: Path) -> None:
    data = probe_data(tmp_path)
    info = runtime.runtime_info(json.dumps(data), arch="x86_64")
    write(info.executable, "base")
    write(info.stdlib / "os.py", "stdlib")
    write(info.dynload / "_dbus.so", "stdlib extension")
    for directory in ("site-packages", "dist-packages", "nested/site-packages"):
        write(info.stdlib / directory / "PySide6/__init__.py", "host Qt")
        write(info.stdlib / directory / "openrazer/__init__.py", "host OpenRazer")
    write(info.stdlib / "__pycache__/os.pyc")
    site = tmp_path / "venv/lib/python3.12/site-packages"
    write(site / "PySide6/__init__.py", "bundled Qt")
    write(site / "dbus/__init__.py", "bundled dbus")
    write(site / "naga_control/adapters/openrazer/__init__.py", "application adapter")
    write(site / "openrazer/__init__.py")
    write(site / "openrazer_client-1.dist-info/METADATA")
    write(site / "pip/__init__.py")
    appdir = tmp_path / "AppDir"
    runtime.copy_runtime(appdir=appdir, venv=tmp_path / "venv", info=info, libpython=None)
    bundled = appdir / "usr/lib/python3.12"
    assert (bundled / "os.py").read_text() == "stdlib"
    assert (bundled / "site-packages/PySide6/__init__.py").read_text() == "bundled Qt"
    assert (bundled / "site-packages/dbus/__init__.py").read_text() == "bundled dbus"
    assert not (bundled / "dist-packages").exists()
    assert not (bundled / "nested/site-packages").exists()
    assert not (bundled / "site-packages/openrazer").exists()
    assert not (bundled / "site-packages/openrazer_client-1.dist-info").exists()
    assert (
        bundled / "site-packages/naga_control/adapters/openrazer/__init__.py"
    ).read_text() == "application adapter"
    assert not list(appdir.rglob("__pycache__"))
    assert not (bundled / "site-packages/pip").exists()


def test_assets_copy_only_explicit_runtime_payload(tmp_path: Path) -> None:
    root, appdir = tmp_path / "checkout", tmp_path / "AppDir"
    asset_sources(root)
    source_dir = assets.copy_assets(root=root, appdir=appdir)
    assert source_dir == appdir / "usr/share/naga-control/system"
    for relative in assets.SYSTEM_TEMPLATES:
        assert (source_dir / relative).read_bytes() == (root / "system" / relative).read_bytes()
    for size in assets.ICON_SIZES:
        relative = f"icons/hicolor/{size}x{size}/apps/{assets.APP_ID}.png"
        assert (source_dir.parent / "assets" / relative).read_text() == str(size)
        assert (appdir / "usr/share" / relative).read_text() == str(size)
    assert (appdir / "AppRun").stat().st_mode & 0o111
    assert (appdir / ".DirIcon").read_text() == "256"
    assert (appdir / f"{assets.APP_ID}.png").read_text() == "256"
    assert (appdir / f"{assets.APP_ID}.svg").read_text() == "svg"
    assert (appdir / f"{assets.APP_ID}.desktop").is_file()
    assert not list(appdir.rglob("*.py"))
    assert not list(appdir.rglob("unwanted.txt"))
    assert not (source_dir.parent / "packaging").exists()


@pytest.mark.parametrize("arch", ["aarch64", "riscv64", "i686"])
def test_rejects_non_native_arch_overrides(
    assembly: FakeAssembly, monkeypatch: pytest.MonkeyPatch, arch: str
) -> None:
    monkeypatch.setenv("ARCH", arch)
    assert build.appimage_build_runner().exit_code != 0
    assert assembly.calls == []


@pytest.mark.parametrize("arch", ["x86_64", "aarch64"])
def test_accepts_known_native_tool_architectures(
    monkeypatch: pytest.MonkeyPatch, arch: str
) -> None:
    monkeypatch.setenv("ARCH", arch)
    monkeypatch.setattr(runtime.platform, "machine", lambda: arch)
    monkeypatch.setattr(runtime.platform, "system", lambda: "Linux")
    assert runtime.native_arch() == arch


@pytest.mark.parametrize(
    "field,value",
    [
        ("implementation", "pypy"),
        ("platform", "darwin"),
        ("version", [3, 11]),
        ("version", [4, 0]),
        ("version", "3.12"),
        ("arch", "aarch64"),
        ("bits", 32),
        ("gil_disabled", True),
    ],
)
def test_rejects_inconsistent_runtime(tmp_path: Path, field: str, value: object) -> None:
    data = probe_data(tmp_path)
    data[field] = value
    with pytest.raises(ValueError):
        runtime.runtime_info(json.dumps(data), arch="x86_64")


@pytest.mark.parametrize("variable", ["PYVER", "PYTHON_VERSION"])
def test_rejects_version_override(
    assembly: FakeAssembly, monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    monkeypatch.setenv(variable, "3.13")
    result = build.appimage_build_runner()
    assert result.exit_code != 0
    assert "does not match selected runtime" in result.stderr
    assert len(assembly.calls) == 1


def test_accepts_matching_full_version_override(
    assembly: FakeAssembly, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTHON_VERSION", "3.12.0")
    assert build.appimage_build_runner().exit_code == 0


@pytest.mark.parametrize("stage", ["probe", "build", "venv", "pip", "ldd", "tool"])
def test_failure_keeps_complete_logs_and_removes_stale_artifacts(
    assembly: FakeAssembly, stage: str
) -> None:
    artifact = write(build.appimage_path(), "stale image")
    assembly.failure = (
        str(assembly.root / "build/appimage/appimagetool") if stage == "tool" else stage
    )
    result = build.appimage_build_runner()
    assert result.exit_code == 23
    assert "complete failing stdout\n" in result.stdout
    assert "complete stderr\n" in result.stderr
    assert not artifact.exists()
    assert result.command_str.endswith(shlex.join(assembly.calls[-1]))


@pytest.mark.parametrize("empty", [False, True])
def test_tool_success_requires_fresh_nonempty_artifact(assembly: FakeAssembly, empty: bool) -> None:
    artifact = write(build.appimage_path(), "stale image")
    assembly.produce_artifact = empty
    assembly.empty_artifact = empty
    result = build.appimage_build_runner()
    assert result.exit_code != 0
    assert "Expected nonempty AppImage" in result.stderr
    assert not artifact.exists()


def test_stale_wheel_cannot_mask_failed_wheel_build(assembly: FakeAssembly) -> None:
    write(assembly.root / "build/appimage/naga_control-stale.whl")
    assembly.produce_wheel = False
    result = build.appimage_build_runner()
    assert result.exit_code != 0
    assert "exactly one freshly built" in result.stderr
    assert len(assembly.calls) == 2


def test_spawn_error_is_logged(assembly: FakeAssembly, monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(args: list[str], *, cwd: str, env_overrides: dict[str, str]) -> RunResult:
        raise FileNotFoundError("missing selected interpreter")

    monkeypatch.setattr(build, "run", unavailable)
    result = build.appimage_build_runner()
    assert result.exit_code != 0
    assert "missing selected interpreter" in result.stderr
    assert sys.executable in result.command_str


def test_runtime_supports_native_lib64_layout(tmp_path: Path) -> None:
    data = probe_data(tmp_path)
    data["platlibdir"] = "lib64"
    info = runtime.runtime_info(json.dumps(data), arch="x86_64")
    write(info.executable)
    write(info.dynload / "_test.so")
    write(tmp_path / "venv/lib/python3.12/site-packages/dbus_next/__init__.py")
    write(tmp_path / "venv/lib64/python3.12/site-packages/PySide6/__init__.py", "bundled Qt")
    appdir = tmp_path / "AppDir"
    runtime.copy_runtime(appdir=appdir, venv=tmp_path / "venv", info=info, libpython=None)
    assert (appdir / "usr/lib64").readlink() == Path("lib")
    assert (appdir / "usr/lib64/python3.12/site-packages/dbus_next/__init__.py").is_file()
    assert (
        appdir / "usr/lib64/python3.12/site-packages/PySide6/__init__.py"
    ).read_text() == "bundled Qt"


def test_native_linux_and_known_tools_are_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARCH", raising=False)
    monkeypatch.setattr(runtime.platform, "system", lambda: "Darwin")
    with pytest.raises(ValueError, match="requires Linux"):
        runtime.native_arch()
    monkeypatch.setattr(runtime.platform, "system", lambda: "Linux")
    monkeypatch.setattr(runtime.platform, "machine", lambda: "riscv64")
    with pytest.raises(ValueError, match="Unsupported AppImage architecture"):
        runtime.native_arch()


def test_asset_failure_keeps_earlier_command_logs(assembly: FakeAssembly) -> None:
    (assembly.root / "buildpython/steps/appimage/AppRun").unlink()
    result = build.appimage_build_runner()
    assert result.exit_code != 0
    assert "FileNotFoundError" in result.stderr and "AppRun" in result.stderr
    assert "pip stdout" in result.stdout
    assert not build.appimage_path().exists()


def test_unresolved_linked_libpython_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unresolved linked libpython"):
        runtime.linked_libpython("libpython3.12.so.1.0 => not found")


@pytest.mark.parametrize("matches", [False, True])
def test_download_verifies_checksum_before_exposing_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, matches: bool
) -> None:
    def download(url: str, *, timeout: int) -> io.BytesIO:
        assert "/1.9.1/appimagetool-x86_64.AppImage" in url
        assert timeout == 120
        return io.BytesIO(b"fake tool")

    monkeypatch.setattr(tool, "urlopen", download)
    if matches:
        import hashlib

        monkeypatch.setitem(
            tool.APPIMAGETOOL_SHA256, "x86_64", hashlib.sha256(b"fake tool").hexdigest()
        )
        target = tool.download_appimagetool(work=tmp_path, arch="x86_64")
        assert target.read_bytes() == b"fake tool"
        assert target.stat().st_mode & 0o111
    else:
        with pytest.raises(ValueError, match="SHA256 mismatch"):
            tool.download_appimagetool(work=tmp_path, arch="x86_64")
        assert not (tmp_path / "appimagetool").exists()
    assert not (tmp_path / "appimagetool.download").exists()
