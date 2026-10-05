"""Select native CPython and assemble it without importing host third-party code."""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from .tool import APPIMAGETOOL_SHA256

RUNTIME_PROBE = """
import json, platform, struct, sys, sysconfig
print(json.dumps({
    "implementation": sys.implementation.name,
    "platform": sys.platform,
    "arch": platform.machine(),
    "bits": struct.calcsize("P") * 8,
    "version": list(sys.version_info[:2]),
    "full_version": platform.python_version(),
    "executable": sys._base_executable,
    "stdlib": sysconfig.get_path("stdlib"),
    "dynload": sysconfig.get_config_var("DESTSHARED"),
    "platlibdir": sys.platlibdir,
    "gil_disabled": bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
}))
"""


@dataclass(frozen=True)
class RuntimeInfo:
    executable: Path
    stdlib: Path
    dynload: Path
    version: str
    arch: str
    platlibdir: str


def native_arch() -> str:
    arch = os.environ.get("ARCH") or platform.machine()
    if platform.system() != "Linux":
        raise ValueError("AppImage assembly requires Linux")
    if arch != platform.machine():
        raise ValueError(f"ARCH={arch} does not match native architecture {platform.machine()}")
    if arch not in APPIMAGETOOL_SHA256:
        raise ValueError(f"Unsupported AppImage architecture: {arch}")
    return arch


def selected_python() -> str:
    # A venv executable may be a copy, not a symlink; resolve its base via the probe.
    return os.environ.get("PYTHON_BIN") or sys.executable


def runtime_info(output: str, *, arch: str) -> RuntimeInfo:
    data = cast(dict[str, object], json.loads(output))
    version = data.get("version")
    if not isinstance(version, list) or len(cast(list[object], version)) != 2:
        raise ValueError("CPython probe did not report a major/minor version")
    parts = cast(list[object], version)
    major, minor = parts
    if not isinstance(major, int) or not isinstance(minor, int) or (major, minor) < (3, 12):
        raise ValueError("AppImage runtime requires CPython >= 3.12")
    if major != 3 or data.get("implementation") != "cpython" or data.get("platform") != "linux":
        raise ValueError("AppImage runtime requires Linux CPython 3.12 or newer")
    if data.get("arch") != arch or data.get("bits") != 64:
        raise ValueError(f"Selected Python runtime does not match native architecture {arch}")
    if data.get("gil_disabled") is not False:
        raise ValueError(
            "Free-threaded CPython runtimes are not supported by this AppImage builder"
        )
    pyver = f"{major}.{minor}"
    for variable in ("PYVER", "PYTHON_VERSION"):
        override = os.environ.get(variable)
        if override and override not in (pyver, data.get("full_version")):
            raise ValueError(f"{variable}={override} does not match selected runtime {pyver}")
    paths: list[Path] = []
    for field in ("executable", "stdlib", "dynload"):
        value = data.get(field)
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError(f"CPython probe did not report an absolute {field} path")
        paths.append(Path(value))
    platlibdir = data.get("platlibdir")
    if platlibdir not in ("lib", "lib64"):
        raise ValueError(f"Unsupported CPython library directory: {platlibdir}")
    return RuntimeInfo(paths[0], paths[1], paths[2], pyver, arch, cast(str, platlibdir))


def linked_libpython(output: str) -> Path | None:
    for line in output.splitlines():
        fields = line.split()
        if fields and fields[0].startswith("libpython"):
            if len(fields) < 3 or fields[1] != "=>" or not Path(fields[2]).is_absolute():
                raise ValueError(f"Unresolved linked libpython: {line.strip()}")
            return Path(fields[2])
    return None


def copy_runtime(*, appdir: Path, venv: Path, info: RuntimeInfo, libpython: Path | None) -> None:
    """Copy stdlib first, then only dependencies installed in the fresh staging venv."""
    lib = appdir / "usr/lib"
    stdlib = lib / f"python{info.version}"
    ignore = shutil.ignore_patterns("site-packages", "dist-packages", "__pycache__", "*.pyc")
    shutil.copytree(info.stdlib, stdlib, ignore=ignore)
    if not info.dynload.is_dir():
        raise FileNotFoundError(f"Missing CPython extension library directory: {info.dynload}")
    if info.dynload != info.stdlib / "lib-dynload":
        shutil.copytree(info.dynload, stdlib / "lib-dynload", dirs_exist_ok=True, ignore=ignore)
    site = stdlib / "site-packages"
    site_sources = {
        (venv / directory / f"python{info.version}/site-packages").resolve()
        for directory in ("lib", info.platlibdir)
    }

    def ignore_dependencies(directory: str, names: list[str]) -> set[str]:
        ignored = set(
            shutil.ignore_patterns("__pycache__", "*.pyc", "pip", "pip-*.dist-info")(
                directory, names
            )
        )
        if Path(directory).resolve() in site_sources:
            ignored.update(name for name in names if name.startswith("openrazer"))
        return ignored

    for source in sorted(site_sources):
        if source.is_dir():
            shutil.copytree(
                source,
                site,
                dirs_exist_ok=True,
                ignore=ignore_dependencies,
            )
    if not site.is_dir():
        raise FileNotFoundError(f"Missing staging venv dependencies under {venv}")
    if info.platlibdir != "lib":
        (appdir / "usr" / info.platlibdir).symlink_to("lib", target_is_directory=True)
    executable = appdir / "usr/bin/python3"
    executable.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(info.executable, executable)
    if libpython is not None:
        shutil.copy2(libpython, lib / libpython.name)
