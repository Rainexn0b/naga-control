"""Shared assembly fakes for AppImage build tests (fake commands only)."""

import json
import shlex
from dataclasses import dataclass, field
from pathlib import Path

from buildpython.steps.appimage import assets
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
