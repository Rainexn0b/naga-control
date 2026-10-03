"""Manual, non-blocking release checks with a persisted pre-release channel."""

import asyncio
from collections.abc import Callable
from contextlib import suppress
from threading import Thread
from typing import cast

from packaging.version import InvalidVersion, Version
from PySide6.QtCore import QSettings, QStandardPaths, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from naga_control.gui.releases import (
    Release,
    UpdateCheckError,
    fetch_releases,
    installed_version,
    latest_release,
)
from naga_control.gui.worker import Runner


class VersionPanel(QWidget):
    """Check GitHub only on user request; never install or change hardware state."""

    checked = Signal(int, object, str)

    def __init__(
        self,
        run: Runner,
        *,
        settings: QSettings | None = None,
        current_version: str | None = None,
        fetcher: Callable[[], tuple[Release, ...]] = fetch_releases,
    ) -> None:
        super().__init__()
        self._run = run
        self._fetcher = fetcher
        if settings is None:
            config = QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.GenericConfigLocation
            )
            settings = QSettings(f"{config}/naga-control/gui.ini", QSettings.Format.IniFormat)
        self._settings = settings
        self._current_version = (
            current_version if current_version is not None else installed_version()
        )
        self._releases: tuple[Release, ...] | None = None
        self._candidate: Release | None = None
        self._request_id = 0
        self._checking = False
        self.checked.connect(self._show_result, Qt.ConnectionType.QueuedConnection)

        self.installed_label = QLabel(self._current_version)
        self.stable_label = QLabel("Not checked")
        self.prerelease_label = QLabel("Not checked")
        self.include_prereleases = QCheckBox("Include pre-releases")
        self.include_prereleases.setChecked(
            bool(self._settings.value("updates/include_prereleases", False, type=bool))
        )
        self.include_prereleases.toggled.connect(self._channel_changed)
        self.status_label = QLabel("Checks are manual. No updates are installed automatically.")
        self.status_label.setWordWrap(True)
        self.check_button = QPushButton("Check for updates")
        self.release_button = QPushButton("Release notes")
        self.release_button.setEnabled(False)
        self.check_button.clicked.connect(self.check_updates)
        self.release_button.clicked.connect(self._open_release)

        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.addRow("Installed version", self.installed_label)
        form.addRow("Latest stable", self.stable_label)
        form.addRow("Latest pre-release", self.prerelease_label)
        buttons = QHBoxLayout()
        buttons.addWidget(self.check_button)
        buttons.addWidget(self.release_button)
        buttons.addStretch()
        column = QVBoxLayout(self)
        column.addLayout(form)
        column.addWidget(self.include_prereleases)
        column.addWidget(self.status_label)
        column.addLayout(buttons)

    def check_updates(self) -> None:
        if self._checking:
            return
        self._checking = True
        self._request_id += 1
        request_id = self._request_id
        self.check_button.setEnabled(False)
        self.release_button.setEnabled(False)
        self.status_label.setText("Checking GitHub releases...")
        try:
            self._run(lambda: self._fetch(request_id))
        except RuntimeError:
            self._show_result(request_id, (), "The update-check worker is unavailable. Try again.")

    async def _fetch(self, request_id: int) -> None:
        loop = asyncio.get_running_loop()
        result: asyncio.Future[tuple[tuple[Release, ...], str]] = loop.create_future()

        def deliver(releases: tuple[Release, ...], error: str) -> None:
            if not result.done():
                result.set_result((releases, error))

        def fetch() -> None:
            releases: tuple[Release, ...] = ()
            error = ""
            try:
                releases = self._fetcher()
            except UpdateCheckError as exc:
                error = str(exc)
            except Exception:
                error = "Could not complete the update check. Try again later."
            with suppress(RuntimeError):
                loop.call_soon_threadsafe(deliver, releases, error)

        # A stalled DNS/socket operation must not keep the application alive on quit.
        Thread(target=fetch, name="naga-release-check", daemon=True).start()
        releases, error = await result
        with suppress(RuntimeError):
            self.checked.emit(request_id, releases, error)

    def _show_result(self, request_id: int, payload: object, error: str) -> None:
        if request_id != self._request_id:
            return
        self._checking = False
        self.check_button.setEnabled(True)
        if error:
            self._releases = None
            self._candidate = None
            self.stable_label.setText("Unavailable")
            self.prerelease_label.setText("Unavailable")
            self.status_label.setText(error)
            self.release_button.setEnabled(False)
            return
        self._releases = cast(tuple[Release, ...], payload)
        stable = latest_release(self._releases)
        prerelease = max(
            (release for release in self._releases if release.prerelease),
            key=lambda release: release.version,
            default=None,
        )
        self.stable_label.setText(stable.tag if stable is not None else "None")
        self.prerelease_label.setText(prerelease.tag if prerelease is not None else "None")
        self._update_comparison()

    def _channel_changed(self, include: bool) -> None:
        self._settings.setValue("updates/include_prereleases", include)
        self._update_comparison()

    def _update_comparison(self) -> None:
        if self._releases is None or self._checking:
            return
        self._candidate = latest_release(
            self._releases, include_prereleases=self.include_prereleases.isChecked()
        )
        self.release_button.setEnabled(self._candidate is not None)
        if self._candidate is None:
            self.status_label.setText(
                "No published releases were found."
                if not self._releases
                else "No stable release was found; pre-releases are excluded."
            )
            return
        try:
            current = Version(self._current_version)
        except InvalidVersion:
            self.status_label.setText(
                "Installed version is unknown; open the release notes to compare."
            )
            return
        latest = self._candidate
        if latest.version > current:
            channel = "pre-release" if latest.prerelease else "stable release"
            message = f"Update available: {latest.tag} ({channel})."
        elif latest.version == current:
            message = "You are up to date for the selected channel."
        else:
            message = (
                "Installed version is newer than the selected release; no downgrade suggested."
            )
        self.status_label.setText(message)

    def _open_release(self) -> None:
        if self._candidate is not None and not QDesktopServices.openUrl(QUrl(self._candidate.url)):
            self.status_label.setText(
                "Could not open a browser. Release notes: " + self._candidate.url
            )
