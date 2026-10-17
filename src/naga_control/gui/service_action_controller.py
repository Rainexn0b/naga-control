"""Bounded guard between service restart and config applies (GUI only)."""

from collections.abc import Callable


class ServiceActionGuard:
    """Own restart busy; MainWindow supplies apply checks and editor switch."""

    def __init__(
        self,
        *,
        is_apply_busy: Callable[[], bool],
        set_editors_enabled: Callable[[bool], None],
    ) -> None:
        self._is_apply_busy = is_apply_busy
        self._set_editors_enabled = set_editors_enabled
        self.restart_busy = False

    def can_start_restart(self) -> bool:
        return not self.restart_busy and not self._is_apply_busy()

    def begin_restart(self) -> bool:
        if not self.can_start_restart():
            return False
        self.restart_busy = True
        self._set_editors_enabled(False)
        return True

    def end_restart(self) -> None:
        self.restart_busy = False
        if not self._is_apply_busy():
            self._set_editors_enabled(True)
