"""Application-level controls: login startup and service restart."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from naga_control.gui.autostart import AutostartStatus, AutostartStore
from naga_control.gui.models import ServiceModel
from naga_control.gui.presenter import GuiPresenter
from naga_control.gui.service_action_controller import ServiceActionGuard
from naga_control.gui.service_restart import RestartResult
from naga_control.gui.worker import Runner

logger = logging.getLogger(__name__)

Restarter = Callable[[], Awaitable[RestartResult]]
Confirmer = Callable[[], bool]

_POST_RESTART_REFRESH_TIMEOUT = 10.0
_RECONNECT_UNVERIFIED_DETAIL = "restart reconnect unverified; check status"
_RESTART_INTERRUPTED_ERROR = "Service restart interrupted (outcome uncertain; check status)."
_RESTART_OK_UNVERIFIED_LABEL = (
    "Background service restarted; connection status unverified - check status."
)


@dataclass(frozen=True)
class _RestartDone:
    result: RestartResult
    refresh_ok: bool


def _default_confirm(parent: QWidget) -> bool:
    answer = QMessageBox.question(
        parent if parent.isVisible() else None,
        "Restart background service",
        "Restart naga-control.service only? Mappings pause briefly and held "
        "outputs are released. OpenRazer is not restarted.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return answer == QMessageBox.StandardButton.Yes


class ApplicationPanel(QWidget):
    """Checkbox for tray autostart plus a guarded service-restart button."""

    autostart_ready = Signal(object)
    restart_ready = Signal(object)

    def __init__(
        self,
        presenter: GuiPresenter,
        model: ServiceModel,
        run: Runner,
        *,
        autostart: AutostartStore | None = None,
        restarter: Restarter | None = None,
        confirm: Confirmer | None = None,
        restart_guard: ServiceActionGuard | None = None,
    ) -> None:
        super().__init__()
        self.presenter = presenter
        self.model = model
        self._run = run
        self._autostart = autostart
        self._restarter = restarter
        self._confirm = confirm
        self._guard = restart_guard
        self._autostart_busy = False
        self._restart_busy = False
        self._updating = False
        self._last_verified: AutostartStatus | None = None

        self.autostart_checkbox = QCheckBox("Start Naga Control at login (tray)")
        self.autostart_checkbox.setToolTip(
            "Creates or removes your owned autostart entry. "
            "The mapping service setting is unchanged."
        )
        self.autostart_error = QLabel("")
        self.autostart_error.setWordWrap(True)
        self.restart_button = QPushButton("Restart background service")
        self.restart_button.setToolTip(
            "Restarts naga-control.service only. OpenRazer is not restarted. "
            "Mappings pause briefly and held outputs are released."
        )
        self.restart_status = QLabel("")
        self.restart_status.setWordWrap(True)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(self.autostart_checkbox)
        column.addWidget(self.autostart_error)
        column.addWidget(self.restart_button)
        column.addWidget(self.restart_status)

        self.autostart_ready.connect(self._show_autostart, Qt.ConnectionType.QueuedConnection)
        self.restart_ready.connect(self._show_restart, Qt.ConnectionType.QueuedConnection)
        self.autostart_checkbox.toggled.connect(self._on_autostart_toggled)
        self.restart_button.clicked.connect(self.request_restart)

        self._refresh_enabled()
        if self._autostart is None:
            self.autostart_checkbox.setEnabled(False)
            self.autostart_error.setText("Startup control unavailable.")
        else:
            self._autostart_busy = True
            self._refresh_enabled()
            self.autostart_error.setText("Loading startup preference...")
            try:
                self._run(self._load_autostart)
            except RuntimeError:
                self._autostart_busy = False
                self._revert_checkbox()
                self.autostart_error.setText("Startup worker unavailable.")
                self._refresh_enabled()
        if self._restarter is None:
            self.restart_button.setEnabled(False)

    @property
    def _busy(self) -> bool:
        return self._autostart_busy or self._restart_busy

    def _refresh_enabled(self) -> None:
        if self._busy:
            self.autostart_checkbox.setEnabled(False)
            self.restart_button.setEnabled(False)
            return
        self.autostart_checkbox.setEnabled(self._autostart is not None)
        self.restart_button.setEnabled(self._restarter is not None)

    def _revert_checkbox(self) -> None:
        self._updating = True
        try:
            keep = self._last_verified.enabled if self._last_verified is not None else False
            self.autostart_checkbox.setChecked(keep)
        finally:
            self._updating = False

    async def _load_autostart(self) -> None:
        try:
            assert self._autostart is not None
            status = await asyncio.to_thread(self._autostart.load)
        except Exception:
            logger.warning("startup preference load failed", exc_info=True)
            status = None
        try:
            if status is not None:
                self.autostart_ready.emit(status)
            elif self._last_verified is not None:
                last = self._last_verified
                self.autostart_ready.emit(
                    AutostartStatus(
                        enabled=last.enabled,
                        error="Could not read the startup entry (state unknown).",
                        path=last.path,
                        exec_line=last.exec_line,
                    )
                )
            else:
                fallback = Path(__file__).resolve().parent / "autostart.py"
                target = self._autostart.path if self._autostart is not None else fallback
                self.autostart_ready.emit(
                    AutostartStatus(
                        enabled=False,
                        error="Could not read the startup entry.",
                        path=target,
                    )
                )
        except RuntimeError:
            pass

    async def _apply_autostart(self, enabled: bool) -> None:
        try:
            assert self._autostart is not None
            status = await asyncio.to_thread(self._autostart.apply, enabled)
        except Exception:
            logger.warning("startup preference apply failed", exc_info=True)
            status = None
        if status is None:
            try:
                assert self._autostart is not None
                reloaded = await asyncio.to_thread(self._autostart.load)
            except Exception:
                reloaded = None
            if reloaded is not None:
                status = AutostartStatus(
                    enabled=reloaded.enabled,
                    error="Could not update the startup entry.",
                    path=reloaded.path,
                    exec_line=reloaded.exec_line,
                )
            elif self._last_verified is not None:
                last = self._last_verified
                status = AutostartStatus(
                    enabled=last.enabled,
                    error="Could not update the startup entry (state unknown).",
                    path=last.path,
                    exec_line=last.exec_line,
                )
            else:
                fallback = Path(__file__).resolve().parent / "autostart.py"
                target = self._autostart.path if self._autostart is not None else fallback
                status = AutostartStatus(
                    enabled=False,
                    error="Could not update the startup entry.",
                    path=target,
                )
        with contextlib.suppress(RuntimeError):
            self.autostart_ready.emit(status)

    def _on_autostart_toggled(self, checked: bool) -> None:
        if self._updating or self._busy or self._autostart is None:
            return
        self._autostart_busy = True
        self._refresh_enabled()
        self.autostart_error.setText("Applying startup preference...")
        try:
            self._run(lambda: self._apply_autostart(checked))
        except RuntimeError:
            self._autostart_busy = False
            self._revert_checkbox()
            self.autostart_error.setText("Startup worker unavailable.")
            self._refresh_enabled()

    def _show_autostart(self, payload: object) -> None:
        status = cast(AutostartStatus, payload)
        self._autostart_busy = False
        self._last_verified = AutostartStatus(
            enabled=status.enabled, error=None, path=status.path, exec_line=status.exec_line
        )
        self._updating = True
        try:
            self.autostart_checkbox.setChecked(status.enabled)
        finally:
            self._updating = False
        self.autostart_error.setText(status.error or "")
        self._refresh_enabled()

    def request_restart(self) -> None:
        if self._busy or self._restarter is None:
            return
        if self._guard is not None and not self._guard.can_start_restart():
            self.restart_status.setText("Another change is in progress; try again.")
            return
        confirmed = self._confirm() if self._confirm is not None else _default_confirm(self)
        if not confirmed:
            return
        if self._guard is not None and not self._guard.begin_restart():
            self.restart_status.setText("Another change is in progress; try again.")
            return
        self._restart_busy = True
        self._refresh_enabled()
        self.restart_status.setText("Restarting background service...")
        try:
            self._run(self._do_restart)
        except RuntimeError:
            self._restart_busy = False
            if self._guard is not None:
                self._guard.end_restart()
            self.restart_status.setText("Service worker unavailable.")
            self._refresh_enabled()

    async def _do_restart(self) -> None:
        assert self._restarter is not None
        try:
            try:
                result = await self._restarter()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("service restart failed", exc_info=True)
                result = RestartResult(ok=False, error="Service restart failed.")
            try:
                await asyncio.wait_for(self.presenter.refresh(), _POST_RESTART_REFRESH_TIMEOUT)
                refresh_ok = True
            except TimeoutError:
                logger.warning("post-restart refresh timed out")
                try:
                    self.model.mark_unreachable(_RECONNECT_UNVERIFIED_DETAIL)
                except Exception:
                    logger.warning("post-restart unreachable mark failed", exc_info=True)
                refresh_ok = False
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("post-restart refresh failed", exc_info=True)
                try:
                    self.model.mark_unreachable(_RECONNECT_UNVERIFIED_DETAIL)
                except Exception:
                    logger.warning("post-restart unreachable mark failed", exc_info=True)
                refresh_ok = False
            with contextlib.suppress(RuntimeError):
                self.restart_ready.emit(_RestartDone(result=result, refresh_ok=refresh_ok))
        except asyncio.CancelledError:
            uncertain = _RestartDone(
                result=RestartResult(ok=False, error=_RESTART_INTERRUPTED_ERROR),
                refresh_ok=False,
            )
            with contextlib.suppress(Exception):
                self.model.mark_unreachable(_RECONNECT_UNVERIFIED_DETAIL)
            with contextlib.suppress(RuntimeError):
                self.restart_ready.emit(uncertain)
            raise

    def _show_restart(self, payload: object) -> None:
        if isinstance(payload, _RestartDone):
            result = payload.result
            refresh_ok = payload.refresh_ok
        else:
            result = cast(RestartResult, payload)
            refresh_ok = True
        self._restart_busy = False
        if self._guard is not None:
            self._guard.end_restart()
        if result.ok and refresh_ok:
            self.restart_status.setText("Background service restarted.")
        elif result.ok:
            self.restart_status.setText(_RESTART_OK_UNVERIFIED_LABEL)
        else:
            self.restart_status.setText(result.error or "Service restart failed.")
        self._refresh_enabled()
        if self._autostart is not None and not self._busy:
            self._autostart_busy = True
            self._refresh_enabled()
            try:
                self._run(self._load_autostart)
            except RuntimeError:
                self._autostart_busy = False
                self._refresh_enabled()
