"""Suite-wide deterministic Qt lifetime for PySide6 6.12 (tests only).

Contract: snapshot top-level C++ identities before each test and delete
only new top levels after it, on the main thread, draining the
deferred-deletion queue per widget. Shared module fixtures (e.g. the
module-scoped ``qapp``) are preserved because pre-existing top levels are
never touched. No-op when Qt is absent or no QApplication exists, so
non-Qt selections are unaffected. A session-finish drain removes
stragglers while QApplication is still alive, before interpreter shutdown.
Unexpected snapshot/cleanup failures propagate instead of reporting green.
"""

from collections.abc import Iterator

import pytest


def _qt_available() -> bool:
    """Probe Qt presence; only missing PySide6/shiboken6 is optional."""
    import importlib.util

    if importlib.util.find_spec("PySide6") is None:
        return False
    return importlib.util.find_spec("shiboken6") is not None


@pytest.fixture(autouse=True)
def _qt_suite_lifetime() -> Iterator[None]:
    if not _qt_available():
        yield
        return
    from gui_qt_lifetime import (
        cleanup_new_top_levels,
        current_app,
        drain_after_cleanup,
        snapshot_top_levels,
        stabilize_before_test,
    )

    app = current_app()
    if app is None:
        before: set[int] = set()
        yield
        live = current_app()
        if live is None:
            return
        cleanup_new_top_levels(live, before)
        return
    before = snapshot_top_levels(app)
    had_leaks = len(before) > 0
    if had_leaks:
        stabilize_before_test(app)
        before = snapshot_top_levels(app)
    yield
    live = current_app()
    if live is None:
        return
    cleaned = cleanup_new_top_levels(live, before)
    if had_leaks and cleaned == 0:
        drain_after_cleanup(live)


def pytest_sessionfinish(session: object, exitstatus: object) -> None:
    """Final drain while QApplication is still valid (main thread)."""
    try:
        from gui_qt_lifetime import cleanup_all_top_levels, current_app
    except ModuleNotFoundError as exc:
        if exc.name is not None and exc.name.split(".")[0] in ("PySide6", "shiboken6"):
            return
        raise
    app = current_app()
    if app is None:
        return
    cleanup_all_top_levels(app)
