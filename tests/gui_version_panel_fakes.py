"""Shared fixtures and doubles for version-panel tests."""

import os
from collections.abc import Callable, Iterator
from contextlib import suppress
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui_qt_lifetime import close_widget_now
from gui_qt_lifetime import drain_after_cleanup as _drain
from gui_qt_lifetime import stabilize_before_test as _stabilize
from gui_support import sync_run
from PySide6.QtCore import QSettings
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication

from naga_control.gui import releases
from naga_control.gui.releases import Release, parse_releases
from naga_control.gui.version_panel import VersionPanel
from naga_control.gui.worker import LoopWorker

_live_panels: list[VersionPanel] = []


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return cast(QApplication, QApplication.instance() or QApplication([]))


@pytest.fixture(autouse=True)
def no_http(monkeypatch: pytest.MonkeyPatch) -> Iterator[Mock]:
    http = Mock(side_effect=AssertionError("Unexpected HTTP request"))
    monkeypatch.setattr(releases.request, "urlopen", http)
    yield http
    http.assert_not_called()


@pytest.fixture(autouse=True)
def browser(monkeypatch: pytest.MonkeyPatch) -> Mock:
    mock = Mock(return_value=True)
    monkeypatch.setattr(QDesktopServices, "openUrl", mock)
    return mock


@pytest.fixture
def settings(tmp_path: Path) -> QSettings:
    prefs = QSettings(str(tmp_path / "updates.ini"), QSettings.Format.IniFormat)
    prefs.setValue("unrelated", "preserve me")
    prefs.sync()
    return prefs


@pytest.fixture
def worker() -> Iterator[LoopWorker]:
    instance = LoopWorker()
    instance.start()
    try:
        yield instance
    finally:
        instance.stop()
    assert not instance.running


def make_releases(*entries: tuple[str, bool]) -> tuple[Release, ...]:
    base = {"draft": False, "html_url": "https://untrusted.example/download"}
    return parse_releases(
        [{**base, "tag_name": tag, "prerelease": prerelease} for tag, prerelease in entries]
    )


def make_panel(
    settings: QSettings,
    fetcher: Callable[[], tuple[Release, ...]],
    *,
    current_version: str | None = "0.1.0",
) -> VersionPanel:
    panel = VersionPanel(
        sync_run, settings=settings, current_version=current_version, fetcher=fetcher
    )
    _live_panels.append(panel)
    return panel


def close_panel(panel: VersionPanel, qapp: QApplication) -> None:
    """Destroy a parentless panel deterministically on the Qt main thread.

    Parentless widgets are otherwise freed by CPython garbage collection at an
    arbitrary point. Under PySide6 6.12 that collection can run reentrantly
    inside signal delivery (``QAbstractButton.click``) or at interpreter
    shutdown (``destroyQCoreApplication``) and segfault there. Draining the
    deferred-deletion queue here keeps deletion on the main thread outside
    signal emission.
    """
    with suppress(ValueError):
        _live_panels.remove(panel)
    close_widget_now(panel, qapp)
    with suppress(RuntimeError):
        qapp.processEvents()


@pytest.fixture(autouse=True)
def managed_panels(qapp: QApplication) -> Iterator[None]:
    """Bound panel lifetime to each test to avoid GC-timed Qt deletions."""
    # Collect garbage from earlier tests at a safe point instead of letting it
    # run reentrantly inside this test's signal delivery.
    _stabilize(qapp)
    yield
    while _live_panels:
        close_panel(_live_panels.pop(), qapp)
    _drain(qapp)


def check_panel(panel: VersionPanel, qapp: QApplication) -> None:
    panel.check_button.click()
    # Even a synchronous runner must wait for Qt's queued result delivery.
    assert not panel.check_button.isEnabled()
    assert not panel.release_button.isEnabled()
    assert panel.status_label.text() == "Checking GitHub releases..."
    qapp.processEvents()
    assert panel.check_button.isEnabled()
