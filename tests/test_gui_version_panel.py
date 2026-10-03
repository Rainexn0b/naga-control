import os
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import Future
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui_support import sync_run
from PySide6.QtCore import QSettings, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication

from naga_control.gui import releases
from naga_control.gui.releases import Release, UpdateCheckError, parse_releases
from naga_control.gui.version_panel import VersionPanel
from naga_control.gui.worker import CoroFactory, LoopWorker


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


def _releases(*entries: tuple[str, bool]) -> tuple[Release, ...]:
    base = {"draft": False, "html_url": "https://untrusted.example/download"}
    return parse_releases(
        [{**base, "tag_name": tag, "prerelease": prerelease} for tag, prerelease in entries]
    )


def _panel(
    settings: QSettings,
    fetcher: Callable[[], tuple[Release, ...]],
    *,
    current_version: str | None = "0.1.0",
) -> VersionPanel:
    return VersionPanel(
        sync_run, settings=settings, current_version=current_version, fetcher=fetcher
    )


def _check(panel: VersionPanel, qapp: QApplication) -> None:
    panel.check_button.click()
    # Even a synchronous runner must wait for Qt's queued result delivery.
    assert not panel.check_button.isEnabled()
    assert not panel.release_button.isEnabled()
    assert panel.status_label.text() == "Checking GitHub releases..."
    qapp.processEvents()
    assert panel.check_button.isEnabled()


@pytest.mark.parametrize("missing", [False, True])
def test_construction_is_manual_and_reads_installed_metadata(
    qapp: QApplication,
    settings: QSettings,
    monkeypatch: pytest.MonkeyPatch,
    browser: Mock,
    missing: bool,
) -> None:
    metadata = Mock(return_value="0.2.0")
    if missing:
        metadata.side_effect = releases.metadata.PackageNotFoundError("naga-control")
    monkeypatch.setattr(releases.metadata, "version", metadata)
    fetcher = Mock(return_value=())
    before = Path(settings.fileName()).read_bytes()
    panel = _panel(settings, fetcher, current_version=None)
    qapp.processEvents()
    assert panel.installed_label.text() == ("unknown" if missing else "0.2.0")
    assert panel.stable_label.text() == panel.prerelease_label.text() == "Not checked"
    assert panel.check_button.isEnabled()
    assert not panel.release_button.isEnabled()
    assert not panel.include_prereleases.isChecked()
    assert panel.status_label.text() == "Checks are manual. No updates are installed automatically."
    metadata.assert_called_once_with("naga-control")
    fetcher.assert_not_called()
    browser.assert_not_called()
    settings.sync()
    assert Path(settings.fileName()).read_bytes() == before


@pytest.mark.parametrize(
    ("entries", "stable", "prerelease", "selected", "channel"),
    [
        (
            (("v0.9", False), ("0.12", True), ("v0.11", False)),
            "v0.11",
            "0.12",
            "0.12",
            "pre-release",
        ),
        (
            (("v0.4.0-rc.2", False), ("v0.4.0", False), ("v0.4.0.dev1", False)),
            "v0.4.0",
            "v0.4.0-rc.2",
            "v0.4.0",
            "stable release",
        ),
        ((("v0.4.0", True), ("0.4.0", False)), "0.4.0", "v0.4.0", "0.4.0", "stable release"),
    ],
)
def test_channel_reuses_cache_and_persists_for_a_new_panel(
    qapp: QApplication,
    settings: QSettings,
    browser: Mock,
    entries: tuple[tuple[str, bool], ...],
    stable: str,
    prerelease: str,
    selected: str,
    channel: str,
) -> None:
    fetcher = Mock(return_value=_releases(*entries))
    panel = _panel(settings, fetcher)
    _check(panel, qapp)
    assert panel.stable_label.text() == stable
    assert panel.prerelease_label.text() == prerelease
    assert panel.status_label.text() == f"Update available: {stable} (stable release)."
    assert panel.release_button.isEnabled()
    assert settings.allKeys() == ["unrelated"]
    panel.include_prereleases.setChecked(True)
    assert panel.status_label.text() == f"Update available: {selected} ({channel})."
    panel.include_prereleases.setChecked(False)
    assert panel.status_label.text() == f"Update available: {stable} (stable release)."
    panel.include_prereleases.setChecked(True)
    settings.sync()
    fresh = QSettings(settings.fileName(), QSettings.Format.IniFormat)
    reopened = _panel(fresh, fetcher)
    qapp.processEvents()
    assert reopened.include_prereleases.isChecked()
    assert reopened.stable_label.text() == "Not checked"
    assert fresh.value("unrelated") == "preserve me"
    assert fresh.value("updates/include_prereleases", type=bool) is True
    fetcher.assert_called_once_with()
    browser.assert_not_called()


@pytest.mark.parametrize(
    ("current", "message"),
    [
        ("0.4.0", "You are up to date for the selected channel."),
        ("0.5.0", "Installed version is newer than the selected release; no downgrade suggested."),
        ("unknown", "Installed version is unknown; open the release notes to compare."),
        ("not-a-version", "Installed version is unknown; open the release notes to compare."),
    ],
)
def test_installed_version_comparison_is_safe(
    qapp: QApplication,
    settings: QSettings,
    browser: Mock,
    current: str,
    message: str,
) -> None:
    panel = _panel(settings, lambda: _releases(("v0.4.0", False)), current_version=current)
    _check(panel, qapp)
    assert panel.installed_label.text() == current
    assert panel.prerelease_label.text() == "None"
    assert panel.status_label.text() == message
    panel.include_prereleases.setChecked(True)
    assert panel.status_label.text() == message
    browser.assert_not_called()


@pytest.mark.parametrize("only_prereleases", [False, True])
def test_empty_or_prerelease_only_results(
    qapp: QApplication,
    settings: QSettings,
    browser: Mock,
    only_prereleases: bool,
) -> None:
    fetcher = Mock(return_value=_releases(("v0.3.0rc1", False)) if only_prereleases else ())
    panel = _panel(settings, fetcher)
    _check(panel, qapp)
    assert panel.stable_label.text() == "None"
    assert panel.prerelease_label.text() == ("v0.3.0rc1" if only_prereleases else "None")
    assert not panel.release_button.isEnabled()
    assert panel.status_label.text() == (
        "No stable release was found; pre-releases are excluded."
        if only_prereleases
        else "No published releases were found."
    )
    panel.include_prereleases.setChecked(True)
    assert panel.release_button.isEnabled() is only_prereleases
    assert panel.status_label.text() == (
        "Update available: v0.3.0rc1 (pre-release)."
        if only_prereleases
        else "No published releases were found."
    )
    fetcher.assert_called_once_with()
    browser.assert_not_called()


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (
            UpdateCheckError("Could not connect to GitHub. Try again."),
            "Could not connect to GitHub. Try again.",
        ),
        (ValueError("private diagnostic"), "Could not complete the update check. Try again later."),
    ],
)
def test_failure_clears_cached_results_and_allows_manual_retry_without_writes(
    qapp: QApplication,
    settings: QSettings,
    browser: Mock,
    failure: Exception,
    message: str,
) -> None:
    good = _releases(("v0.4.0", False))
    fetcher = Mock(side_effect=[good, failure, good])
    before = Path(settings.fileName()).read_bytes()
    panel = _panel(settings, fetcher)
    _check(panel, qapp)
    _check(panel, qapp)
    assert panel.stable_label.text() == panel.prerelease_label.text() == "Unavailable"
    assert panel.status_label.text() == message
    assert not panel.release_button.isEnabled()
    panel.release_button.click()
    qapp.processEvents()
    assert fetcher.call_count == 2
    browser.assert_not_called()
    settings.sync()
    assert Path(settings.fileName()).read_bytes() == before
    panel.include_prereleases.setChecked(True)
    assert panel.status_label.text() == message
    assert not panel.release_button.isEnabled()
    _check(panel, qapp)
    assert panel.stable_label.text() == "v0.4.0"
    assert panel.release_button.isEnabled()
    assert fetcher.call_count == 3


@pytest.mark.parametrize("opened", [False, True])
def test_release_notes_open_only_the_canonical_url_on_click(
    qapp: QApplication,
    settings: QSettings,
    browser: Mock,
    opened: bool,
) -> None:
    browser.return_value = opened
    panel = _panel(settings, lambda: _releases(("v0.4.0+local", False)))
    panel.release_button.click()
    _check(panel, qapp)
    browser.assert_not_called()
    previous = panel.status_label.text()
    panel.release_button.click()
    url = "https://github.com/Rainexn0b/naga-control/releases/tag/v0.4.0%2Blocal"
    browser.assert_called_once_with(QUrl(url))
    assert panel.status_label.text() == (
        previous if opened else "Could not open a browser. Release notes: " + url
    )


def test_closed_worker_is_friendly_and_does_not_fetch(
    qapp: QApplication,
    settings: QSettings,
    browser: Mock,
) -> None:
    closed = LoopWorker()
    closed.start()
    closed.stop()

    def run(factory: CoroFactory) -> None:
        closed.submit(factory)

    fetcher = Mock(return_value=())
    panel = VersionPanel(run, settings=settings, current_version="0.1.0", fetcher=fetcher)
    panel.check_button.click()
    qapp.processEvents()
    assert panel.check_button.isEnabled()
    assert not panel.release_button.isEnabled()
    assert panel.stable_label.text() == panel.prerelease_label.text() == "Unavailable"
    assert panel.status_label.text() == "The update-check worker is unavailable. Try again."
    panel.check_button.click()
    assert panel.check_button.isEnabled()
    assert settings.allKeys() == ["unrelated"]
    fetcher.assert_not_called()
    browser.assert_not_called()


def test_real_worker_keeps_qt_responsive_queues_mutations_and_ignores_stale_jobs(
    qapp: QApplication,
    settings: QSettings,
    worker: LoopWorker,
    browser: Mock,
) -> None:
    started, release = threading.Event(), threading.Event()
    fetch_threads: list[int] = []
    deliveries: list[int] = []
    futures: list[Future[object]] = []
    results = (_releases(("v0.2.0", False)), _releases(("v0.3.0", False)))

    class RecordingPanel(VersionPanel):
        def _show_result(self, request_id: int, payload: object, error: str) -> None:
            deliveries.append(threading.get_ident())
            super()._show_result(request_id, payload, error)

    def fetch() -> tuple[Release, ...]:
        index = len(fetch_threads)
        fetch_threads.append(threading.get_ident())
        started.set()
        if not release.wait(5):
            raise TimeoutError("test fetch gate was not released")
        return results[index]

    def run(factory: CoroFactory) -> None:
        futures.append(worker.submit(factory))

    panel = RecordingPanel(run, settings=settings, current_version="0.1.0", fetcher=fetch)
    main_thread = threading.get_ident()
    try:
        panel.check_button.click()
        assert started.wait(5)
        heartbeat: list[int] = []
        QTimer.singleShot(0, lambda: heartbeat.append(threading.get_ident()))
        qapp.processEvents()
        assert heartbeat == [main_thread]
        assert not panel.check_button.isEnabled()
        assert not panel.release_button.isEnabled()
        assert panel.stable_label.text() == "Not checked"
        panel.check_updates()
        panel.include_prereleases.setChecked(True)
        assert len(futures) == 1
        release.set()
        futures[0].result(timeout=5)
        assert deliveries == []
        assert panel.stable_label.text() == "Not checked"
        qapp.processEvents()
        assert panel.stable_label.text() == "v0.2.0"
        assert panel.check_button.isEnabled()

        release.clear()
        started.clear()
        panel.check_button.click()
        assert started.wait(5)
        panel.checked.emit(1, results[0], "late failure")
        qapp.processEvents()
        assert not panel.check_button.isEnabled()
        assert not panel.release_button.isEnabled()
        assert panel.status_label.text() == "Checking GitHub releases..."
        assert panel.stable_label.text() == "v0.2.0"
        release.set()
        futures[1].result(timeout=5)
        assert panel.stable_label.text() == "v0.2.0"
        qapp.processEvents()
        assert panel.stable_label.text() == "v0.3.0"
        panel.checked.emit(1, results[0], "")
        qapp.processEvents()
        assert panel.stable_label.text() == "v0.3.0"
        assert panel.status_label.text() == "Update available: v0.3.0 (stable release)."
        assert panel.check_button.isEnabled() and panel.release_button.isEnabled()
        assert len(fetch_threads) == len(futures) == 2
        assert all(thread != main_thread for thread in fetch_threads)
        assert deliveries == [main_thread] * 4
        browser.assert_not_called()
    finally:
        release.set()
        for future in futures:
            future.result(timeout=5)
        qapp.processEvents()
        panel.close()
