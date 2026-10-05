from __future__ import annotations

import tomllib

from ..utils.import_probe import probe_module_import
from ..utils.paths import repo_root
from ..utils.subproc import RunResult


def import_validation_runner() -> RunResult:
    failures: list[str] = []
    root = repo_root()

    with (root / "pyproject.toml").open("rb") as source:
        scripts = tomllib.load(source)["project"]["scripts"]
    modules = sorted({entry.partition(":")[0] for entry in scripts.values()})

    for mod in modules:
        probe = probe_module_import(mod, cwd=root)
        if not probe.ok:
            failures.append(f"Failed to import {mod}: {probe.error_message}\n{probe.stderr}")

    if failures:
        return RunResult(
            command_str="(internal) import validation",
            stdout="\n".join(failures) + "\n",
            stderr="",
            exit_code=1,
        )

    return RunResult(
        command_str="(internal) import validation",
        stdout=(
            f"Checked entry-point imports: {len(modules)} OK\n"
            + "\n".join(f"  - {m}" for m in modules)
            + "\n"
        ),
        stderr="",
        exit_code=0,
    )
