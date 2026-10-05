from __future__ import annotations

import ast
import tomllib

from ..utils.paths import repo_root
from ..utils.project_metadata import ProjectMetadataError, read_project_dependencies
from ..utils.subproc import RunResult
from .appimage.assets import APP_ID, ICON_SIZES

REQUIRED_FILES = (
    "README.md",
    "LICENSE",
    "pyproject.toml",
    "install.sh",
    "uninstall.sh",
    "scripts/install_user.sh",
    "scripts/uninstall.sh",
    "buildpython/steps/appimage/build.py",
    "buildpython/steps/appimage/AppRun",
    "system/desktop/org.nagacontrol.NagaControl.desktop",
    "system/udev/70-naga-control.rules",
    "system/systemd/user/naga-control.service",
    "system/dbus-1/services/org.nagacontrol.Service1.service",
    "assets/org.nagacontrol.NagaControl.svg",
    *(f"assets/icons/hicolor/{size}x{size}/apps/{APP_ID}.png" for size in ICON_SIZES),
)


def repo_validation_runner() -> RunResult:
    root = repo_root()
    errors = [
        f"Missing required file: {path}" for path in REQUIRED_FILES if not (root / path).is_file()
    ]
    try:
        read_project_dependencies(root / "pyproject.toml")
        with (root / "pyproject.toml").open("rb") as source:
            project = tomllib.load(source)["project"]
        if project["name"] != "naga-control":
            errors.append("pyproject.toml: expected project name naga-control")
        for name, entry in project["scripts"].items():
            module, separator, function = entry.partition(":")
            path = root / "src" / (module.replace(".", "/") + ".py")
            if not separator or not path.is_file():
                errors.append(f"{name}: missing entry-point module {module}")
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            if not any(
                isinstance(node, ast.FunctionDef) and node.name == function for node in tree.body
            ):
                errors.append(f"{name}: missing entry-point function {entry}")
    except (OSError, ValueError, KeyError, TypeError, ProjectMetadataError) as error:
        errors.append(f"Project metadata: {error}")
    return RunResult(
        command_str="(internal) repo validation",
        stdout="\n".join(errors) + "\n"
        if errors
        else "OK: Naga packaging and entry points are present.\n",
        stderr="",
        exit_code=1 if errors else 0,
    )
