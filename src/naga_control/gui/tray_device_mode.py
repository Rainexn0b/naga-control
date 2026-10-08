"""Persistent read-only device-mode submenu; deliberately owns no intent callback."""

from PySide6.QtWidgets import QMenu

from naga_control.gui.models import ServiceModel
from naga_control.gui.profile_mode_view import (
    DEVICE_MODE_HELP,
    MODE_SWITCH_GATE,
    device_mode_view,
)


class TrayDeviceMode:
    """Retain menu/actions and render existing model state, including while offline."""

    def __init__(self, parent: QMenu, model: ServiceModel) -> None:
        self.model = model
        self.menu = parent.addMenu("Device mode")
        self.menu.setToolTipsVisible(True)
        self.menu.menuAction().setToolTip(DEVICE_MODE_HELP)
        self.requested_action = self.menu.addAction("")
        self.observed_action = self.menu.addAction("")
        self.remapping_action = self.menu.addAction("")
        self.error_action = self.menu.addAction("")
        self.menu.addSeparator()
        self.gate_action = self.menu.addAction(MODE_SWITCH_GATE)
        for action in self.menu.actions():
            action.setEnabled(False)
            action.setToolTip(DEVICE_MODE_HELP)
        parent.aboutToShow.connect(self.refresh)
        self.menu.aboutToShow.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        view = device_mode_view(self.model)
        self.requested_action.setText(f"Requested: {view.requested}")
        self.observed_action.setText(f"Observed: {view.observed}")
        self.remapping_action.setText(f"Software remapping: {view.remapping}")
        self.error_action.setText(f"Mode error: {view.error or 'none'}")
        self.error_action.setVisible(view.error is not None)
