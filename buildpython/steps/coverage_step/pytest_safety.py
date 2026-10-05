"""Hardware-independent test policy for build-time pytest invocations."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


def _deny_device_open(event: str, args: tuple[object, ...]) -> None:
    if event != "open" or not args or isinstance(args[0], int):
        return
    path = args[0]
    if not isinstance(path, (str, bytes, os.PathLike)):
        return
    resolved = str(Path(os.fsdecode(os.fspath(path))).resolve())
    if any(
        resolved == prefix or resolved.startswith(prefix + "/")
        for prefix in ("/dev/input", "/dev/uinput")
    ) or resolved.startswith("/dev/hidraw"):
        raise PermissionError("Build tests must not open physical input or output device nodes")


@pytest.hookimpl(tryfirst=True)
def pytest_load_initial_conftests() -> None:
    # Install before conftest/test-module collection can execute hardware code.
    sys.addaudithook(_deny_device_open)


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    excluded = [item for item in items if item.get_closest_marker("hardware") is not None]
    if excluded:
        items[:] = [item for item in items if item.get_closest_marker("hardware") is None]
        config.hook.pytest_deselected(items=excluded)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    if item.get_closest_marker("hardware") is not None:
        pytest.skip("Hardware tests are never allowed in a build validation run")
