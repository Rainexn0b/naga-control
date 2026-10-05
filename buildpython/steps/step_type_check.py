from __future__ import annotations

from ..utils.paths import repo_root
from ..utils.subproc import RunResult, python_exe, run


def pyright_runner() -> RunResult:
    root = repo_root()

    return run(
        [
            python_exe(),
            "-m",
            "pyright",
        ],
        cwd=str(root),
    )
