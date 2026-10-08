"""Qt lifetime ownership for parentless version panels (fake-only)."""

import gc
import os
import threading
from unittest.mock import Mock

import pytest
import shiboken6

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui_qt_lifetime import cleanup_all_top_levels as _clean_all
from gui_qt_lifetime import cleanup_new_top_levels as _clean_new
from gui_qt_lifetime import close_widget_now as _close_now
from gui_qt_lifetime import drain_after_cleanup as _drain
from gui_qt_lifetime import on_main_thread as _on_main
from gui_qt_lifetime import snapshot_top_levels as _snapshot
from gui_qt_lifetime import stabilize_before_test as _stabilize
from gui_version_panel_fakes import check_panel as _check
from gui_version_panel_fakes import close_panel as _close
from gui_version_panel_fakes import make_panel as _panel
from gui_version_panel_fakes import make_releases as _releases
from gui_version_panel_fakes import managed_panels as managed_panels
from gui_version_panel_fakes import qapp as qapp
from gui_version_panel_fakes import settings as settings
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QWidget

from naga_control.gui.version_panel import VersionPanel


def live_panels() -> int:
    return sum(
        1
        for candidate in gc.get_objects()
        if isinstance(candidate, VersionPanel) and shiboken6.isValid(candidate)
    )


def test_close_panel_destroys_the_wrapper(qapp: QApplication, settings: QSettings) -> None:
    panel = _panel(settings, lambda: _releases(("v0.4.0", False)))
    _check(panel, qapp)
    assert shiboken6.isValid(panel)
    _close(panel, qapp)
    assert not shiboken6.isValid(panel)


def test_close_panel_is_idempotent(qapp: QApplication, settings: QSettings) -> None:
    panel = _panel(settings, lambda: ())
    _close(panel, qapp)
    _close(panel, qapp)
    assert not shiboken6.isValid(panel)


def test_repeated_checks_do_not_accumulate_wrappers(
    qapp: QApplication, settings: QSettings
) -> None:
    gc.collect()
    baseline = live_panels()
    for _ in range(5):
        panel = _panel(settings, lambda: _releases(("v0.4.0", False)))
        _check(panel, qapp)
        _close(panel, qapp)
    gc.collect()
    qapp.processEvents()
    assert live_panels() <= baseline


def test_helper_runs_on_the_main_thread(qapp: QApplication) -> None:
    assert _on_main(qapp)
    _stabilize(qapp)
    _drain(qapp)


def test_helper_cleans_only_new_top_levels(qapp: QApplication) -> None:
    _stabilize(qapp)
    keeper = QWidget()
    keeper.setObjectName("lifetime-keeper")
    try:
        before = _snapshot(qapp)
        leaked = QWidget()
        leaked.setObjectName("lifetime-new")
        assert shiboken6.isValid(keeper)
        assert shiboken6.isValid(leaked)
        cleaned = _clean_new(qapp, before)
        assert cleaned == 1
        assert shiboken6.isValid(keeper)
        assert not shiboken6.isValid(leaked)
    finally:
        _close_now(keeper, qapp)
        _drain(qapp)
    assert shiboken6.isValid(keeper) is False


def test_helper_close_is_idempotent_and_thread_checked(qapp: QApplication) -> None:
    widget = QWidget()
    assert _close_now(widget, qapp)
    qapp.processEvents()
    assert not shiboken6.isValid(widget)
    assert _close_now(widget, qapp) is False


def test_close_propagates_unexpected_errors(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget = QWidget()
    assert shiboken6.isValid(widget)

    def _boom() -> None:
        raise ValueError("unexpected-close")

    monkeypatch.setattr(widget, "close", _boom)
    with pytest.raises(ValueError, match="unexpected-close"):
        _close_now(widget, qapp)
    assert shiboken6.isValid(widget)


def test_snapshot_propagates_unexpected_errors(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(QApplication, "topLevelWidgets", Mock(side_effect=ValueError("boom")))
    with pytest.raises(ValueError, match="boom"):
        _snapshot(qapp)


@pytest.mark.parametrize("method", ["close", "deleteLater", "send"])
def test_live_runtime_error_surfaces(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    widget = QWidget()
    assert shiboken6.isValid(widget)

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("live-boom")

    if method == "send":
        monkeypatch.setattr(QApplication, "sendPostedEvents", _boom)
    else:
        monkeypatch.setattr(widget, method, _boom)
    with pytest.raises(RuntimeError, match="live-boom"):
        _close_now(widget, qapp)
    assert shiboken6.isValid(widget)


def test_parent_child_deletion_counts_without_false_failure(qapp: QApplication) -> None:
    _stabilize(qapp)
    before = _snapshot(qapp)
    parent = QWidget()
    parent.setObjectName("lifetime-parent")
    child = QWidget(parent)
    child.setWindowFlag(Qt.WindowType.Window, True)
    child.setObjectName("lifetime-child-window")
    assert shiboken6.isValid(parent)
    assert shiboken6.isValid(child)
    assert child.isWindow()
    assert _clean_new(qapp, before) == 2
    assert not shiboken6.isValid(parent)
    assert not shiboken6.isValid(child)


def test_cross_thread_refuses_deletion(qapp: QApplication) -> None:
    widget = QWidget()
    try:
        outcomes: list[bool] = []

        def _from_worker() -> None:
            outcomes.append(_close_now(widget, qapp))

        worker_thread = threading.Thread(target=_from_worker)
        worker_thread.start()
        worker_thread.join(timeout=5)
        assert outcomes == [False]
        assert shiboken6.isValid(widget)
    finally:
        assert _close_now(widget, qapp)
        _drain(qapp)
    assert not shiboken6.isValid(widget)


def test_cleanup_counts_only_actually_destroyed(qapp: QApplication) -> None:
    _stabilize(qapp)
    before = _snapshot(qapp)
    first = QWidget()
    second = QWidget()
    assert _close_now(first, qapp)
    _drain(qapp)
    assert not shiboken6.isValid(first)
    assert shiboken6.isValid(second)
    assert _clean_new(qapp, before) == 1
    assert not shiboken6.isValid(second)


def test_cleanup_all_raises_when_deletion_blocked(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget = QWidget()
    assert shiboken6.isValid(widget)

    def _noop(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(QApplication, "sendPostedEvents", _noop)
    with pytest.raises(AssertionError, match="left"):
        _clean_all(qapp)
    assert shiboken6.isValid(widget)
    monkeypatch.undo()
    assert _clean_all(qapp) >= 1
    assert not shiboken6.isValid(widget)


def test_sessionfinish_propagates_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import conftest as session_conftest

    failing = Mock(side_effect=AssertionError("leftover"))
    monkeypatch.setattr("gui_qt_lifetime.cleanup_all_top_levels", failing)
    with pytest.raises(AssertionError, match="leftover"):
        session_conftest.pytest_sessionfinish(Mock(), 0)


def test_repeated_widget_cleanup_does_not_accumulate(qapp: QApplication) -> None:
    _stabilize(qapp)
    baseline = len(QApplication.topLevelWidgets())
    for _ in range(10):
        before = _snapshot(qapp)
        widget = QWidget()
        assert len(QApplication.topLevelWidgets()) == baseline + 1
        assert _clean_new(qapp, before) == 1
        assert not shiboken6.isValid(widget)
    _drain(qapp)
    assert len(QApplication.topLevelWidgets()) == baseline
    assert _clean_all(qapp) == 0
