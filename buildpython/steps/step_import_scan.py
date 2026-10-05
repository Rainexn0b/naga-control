from __future__ import annotations

import ast
import sys
from pathlib import Path

from ..utils.import_probe import probe_module_import
from ..utils.paths import repo_root
from ..utils.subproc import RunResult

OPTIONAL_TOPLEVEL = {
    "openrazer",  # host integration, deliberately not a PyPI dependency
    "dbus",  # host OpenRazer binding, bundled by the AppImage builder
    "coverage",  # optional analysis tool
    "vulture",  # optional analysis tool
}


def _stdlib_modules() -> set[str]:
    return set(sys.stdlib_module_names)


def _iter_py_files() -> list[Path]:
    root = repo_root()
    files: list[Path] = []

    for base in [root / "src" / "naga_control", root / "buildpython", root / "scripts"]:
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            # Exclude tests from import-scan (they may reference optional hardware/integration modules)
            if "tests" in p.relative_to(base).parts or p.name.startswith("test_"):
                continue
            files.append(p)

    return files


def _parse_imports(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))

    imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name.split(".", 1)[0]
                imports.add(name)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            # skip relative imports
            if getattr(node, "level", 0):
                continue
            name = node.module.split(".", 1)[0]
            imports.add(name)

    return imports


def import_scan_runner() -> RunResult:
    root = repo_root()

    stdlib = _stdlib_modules()

    all_imports: set[str] = set()
    files = _iter_py_files()
    scan_errors: list[str] = []
    if not files:
        scan_errors.append("No source files found to scan")
    for p in files:
        try:
            all_imports.update(_parse_imports(p))
        except (OSError, UnicodeError, SyntaxError) as exc:
            scan_errors.append(f"Cannot scan {p}: {exc}")

    # Filter out obvious project-internal top-levels
    ignore = {"naga_control", "buildpython"}
    candidates = sorted(i for i in all_imports if i not in stdlib and i not in ignore)

    missing: list[str] = []
    optional_missing: list[str] = []
    ok: list[str] = []
    probe_diagnostics: list[str] = list(scan_errors)

    for name in candidates:
        probe = probe_module_import(name, cwd=root)
        if probe.ok:
            ok.append(name)
            continue

        if probe.stderr.strip():
            probe_diagnostics.append(f"--- {name} ---\n{probe.stderr.rstrip()}")
        detail = f"{name} ({probe.failure_detail})"
        if name in OPTIONAL_TOPLEVEL:
            optional_missing.append(detail)
        else:
            missing.append(detail)

    stdout_lines: list[str] = []
    stdout_lines.append("Import scan")
    stdout_lines.append("")
    stdout_lines.append(f"Modules seen: {len(candidates)}")
    stdout_lines.append(f"Source files discovered: {len(files)} | Scan errors: {len(scan_errors)}")
    stdout_lines.append(
        "Scope: external top-level imports; excludes stdlib and project-internal imports."
    )

    if missing:
        stdout_lines.append("")
        stdout_lines.append("Missing required imports:")
        stdout_lines.extend(f"  - {m}" for m in missing)

    if optional_missing:
        stdout_lines.append("")
        stdout_lines.append("Missing optional imports:")
        stdout_lines.extend(f"  - {m}" for m in optional_missing)

    stdout_lines.append("")
    stdout_lines.append("OK:")
    stdout_lines.extend(f"  - {m}" for m in ok)

    exit_code = 1 if missing or scan_errors else 0

    return RunResult(
        command_str="(internal) import scan",
        stdout="\n".join(stdout_lines) + "\n",
        stderr="\n\n".join(probe_diagnostics) + ("\n" if probe_diagnostics else ""),
        exit_code=exit_code,
    )
