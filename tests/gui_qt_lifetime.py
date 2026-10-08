"""Deterministic Qt test lifetime for PySide6 6.12 (fake-only, tests only).

Contract (tests only, never production code):

- Qt objects are owned by the main thread. Deletion must run on the main
  thread, outside signal emission, before interpreter shutdown.
- Parentless widgets are otherwise freed by CPython garbage collection at an
  arbitrary point. Under PySide6 6.12 that collection can run reentrantly
  inside ``QAbstractButton.click`` (``runDeletionInMainThread``) or at
  interpreter shutdown (``destroyQCoreApplication``/``visitAllPyObjects``)
  and segfault there.
- ``deleteLater`` alone is not enough: ``processEvents`` does not drain the
  deferred-deletion queue. Each widget needs ``sendPostedEvents`` with
  ``DeferredDelete`` on the main thread, then ``processEvents``.
- Callers snapshot top-level C++ identities before a test and delete only
  new top levels after it, so shared module fixtures are never removed
  prematurely. A final session drain removes stragglers while QApplication
  is still alive.
- Only the expected already-deleted race is treated as idempotent: a
  ``RuntimeError`` is suppressed only when the corresponding wrapper/app
  verifies invalid afterwards; a ``RuntimeError`` on a live wrapper/app
  re-raises so cleanup failures surface instead of reporting green.
- Deletion is verified with ``shiboken6.isValid`` after the deferred-delete
  drain. Helpers claim only widgets actually destroyed; parent-child
  auto-deletion counts as destroyed, never as a false failure.
"""

import gc
import threading
from collections.abc import Callable

import shiboken6
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QWidget


def _deleted(obj: QWidget | QApplication) -> bool:
    """Check whether a wrapper/app is already deleted (never raises)."""
    try:
        return not shiboken6.isValid(obj)
    except RuntimeError:
        return True


def _ignore_deleted(
    call: Callable[[], object],
    primary: QWidget | QApplication,
    secondary: QWidget | QApplication | None = None,
) -> None:
    """Run a Qt call; suppress ``RuntimeError`` only if deleted.

    A ``RuntimeError`` is the expected already-deleted race only when the
    corresponding wrapper verifies invalid. A ``RuntimeError`` on a live
    wrapper/app re-raises. Every other exception always propagates.
    """
    try:
        call()
    except RuntimeError:
        if _deleted(primary):
            return
        if secondary is not None and _deleted(secondary):
            return
        raise


def current_app() -> QApplication | None:
    """Return the live QApplication, or None when Qt is absent/unstarted."""
    try:
        app = QApplication.instance()
    except RuntimeError:
        return None
    if isinstance(app, QApplication) and shiboken6.isValid(app):
        return app
    return None


def on_main_thread(app: QApplication) -> bool:
    """Check Qt and Python main-thread ownership before deleting."""
    try:
        instance = QApplication.instance()
    except RuntimeError:
        return False
    if instance is None:
        return False
    try:
        return (
            threading.current_thread() is threading.main_thread()
            and app.thread() is instance.thread()
        )
    except RuntimeError:
        return False


def _cpp_key(widget: QWidget) -> int | None:
    if _deleted(widget):
        return None
    try:
        return int(shiboken6.getCppPointer(widget)[0])
    except RuntimeError:
        if _deleted(widget):
            return None
        raise


def _is_valid(widget: QWidget) -> bool:
    try:
        return bool(shiboken6.isValid(widget))
    except RuntimeError:
        return False


def snapshot_top_levels(app: QApplication) -> set[int]:
    """Snapshot live main-thread top-level C++ identities."""
    keys: set[int] = set()
    try:
        widgets = QApplication.topLevelWidgets()
    except RuntimeError:
        if _deleted(app):
            return keys
        raise
    for widget in widgets:
        try:
            if not shiboken6.isValid(widget):
                continue
            if widget.thread() is not app.thread():
                continue
            key = _cpp_key(widget)
        except RuntimeError:
            if _deleted(widget):
                continue
            raise
        if key is not None:
            keys.add(key)
    return keys


def stabilize_before_test(app: QApplication) -> None:
    """Collect garbage at a safe point so it cannot run inside a signal."""
    if not on_main_thread(app):
        return
    gc.collect()
    try:
        app.processEvents()
    except RuntimeError:
        if _deleted(app):
            return
        raise


def drain_after_cleanup(app: QApplication) -> None:
    """Drain queued Qt events and collect wrappers whose C++ is gone."""
    if not on_main_thread(app):
        return
    try:
        app.processEvents()
    except RuntimeError:
        if _deleted(app):
            return
        raise
    gc.collect()
    try:
        app.processEvents()
    except RuntimeError:
        if _deleted(app):
            return
        raise
    gc.collect()


def close_widget_now(widget: QWidget, app: QApplication) -> bool:
    """Close and verify deferred deletion for one main-thread widget.

    Returns True only when the widget is actually destroyed (``isValid``
    is False afterwards). Already-deleted wrappers and cross-thread
    widgets return False without raising. Only the expected
    already-deleted ``RuntimeError`` race is idempotent; every other
    exception propagates.
    """
    try:
        if not shiboken6.isValid(widget):
            return False
    except RuntimeError:
        return False
    try:
        if widget.thread() is not app.thread() or not on_main_thread(app):
            return False
    except RuntimeError:
        return False
    _ignore_deleted(widget.close, widget)
    _ignore_deleted(widget.deleteLater, widget)
    _ignore_deleted(
        lambda: app.sendPostedEvents(widget, QEvent.Type.DeferredDelete),
        widget,
        app,
    )
    return not _is_valid(widget)


def _collect_new(app: QApplication, before: set[int]) -> list[QWidget]:
    try:
        widgets = QApplication.topLevelWidgets()
    except RuntimeError:
        if _deleted(app):
            return []
        raise
    fresh: list[QWidget] = []
    for widget in widgets:
        try:
            if not shiboken6.isValid(widget):
                continue
            if widget.thread() is not app.thread():
                continue
            key = _cpp_key(widget)
        except RuntimeError:
            if _deleted(widget):
                continue
            raise
        if key is not None and key not in before:
            fresh.append(widget)
    return fresh


def cleanup_new_top_levels(app: QApplication, before: set[int]) -> int:
    """Delete new top levels and return how many were actually destroyed."""
    if not on_main_thread(app):
        return 0
    fresh = _collect_new(app, before)
    if not fresh:
        return 0
    for widget in fresh:
        _ignore_deleted(widget.close, widget)
    for widget in fresh:
        _ignore_deleted(widget.deleteLater, widget)
    for widget in fresh:
        _ignore_deleted(
            lambda w=widget: app.sendPostedEvents(w, QEvent.Type.DeferredDelete),
            widget,
            app,
        )
    drain_after_cleanup(app)
    destroyed = 0
    for widget in fresh:
        if not _is_valid(widget):
            destroyed += 1
    return destroyed


def _collect_live(app: QApplication) -> list[QWidget]:
    try:
        widgets = QApplication.topLevelWidgets()
    except RuntimeError:
        if _deleted(app):
            return []
        raise
    live: list[QWidget] = []
    for widget in widgets:
        try:
            if not shiboken6.isValid(widget):
                continue
            if widget.thread() is not app.thread():
                continue
        except RuntimeError:
            if _deleted(widget):
                continue
            raise
        live.append(widget)
    return live


def cleanup_all_top_levels(app: QApplication) -> int:
    """Delete every live main-thread top level; raise when any survive."""
    if not on_main_thread(app):
        return 0
    total = 0
    for _ in range(3):
        live = _collect_live(app)
        if not live:
            break
        for widget in live:
            _ignore_deleted(widget.close, widget)
        for widget in live:
            _ignore_deleted(widget.deleteLater, widget)
        for widget in live:
            _ignore_deleted(
                lambda w=widget: app.sendPostedEvents(w, QEvent.Type.DeferredDelete),
                widget,
                app,
            )
        drain_after_cleanup(app)
        for widget in live:
            if not _is_valid(widget):
                total += 1
    remaining = _collect_live(app)
    still = [widget for widget in remaining if _is_valid(widget)]
    if still:
        raise AssertionError(f"Qt lifetime cleanup left {len(still)} top-level widgets")
    return total
