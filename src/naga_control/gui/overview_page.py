"""Overview page: service state, profile selection, and safe actions."""

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QWidget

from naga_control.config import parse_toml
from naga_control.gui.models import ServiceModel
from naga_control.gui.presenter import GuiPresenter
from naga_control.gui.worker import Runner

logger = logging.getLogger(__name__)


class OverviewPage(QWidget):
    """Show service state; never import evdev or OpenRazer here."""

    model_changed = Signal()

    def __init__(self, presenter: GuiPresenter, model: ServiceModel, run: Runner) -> None:
        super().__init__()
        self.presenter = presenter
        self.model = model
        self._run = run
        self._updating_profiles = False

        self.model.add_listener(self.model_changed.emit)
        self.model_changed.connect(self._update_from_model, Qt.ConnectionType.QueuedConnection)

        self.connection_label = QLabel("connecting…")
        self.status_label = QLabel("unknown")
        self.transport_label = QLabel("unknown")
        self.generation_label = QLabel("unknown")
        self.revision_label = QLabel("unknown")
        self.error_label = QLabel("none")
        self.error_label.setWordWrap(True)
        self.observed_dpi_label = QLabel("unknown")
        self.scroll_mode_label = QLabel("unknown")
        self.poll_rate_label = QLabel("unknown")
        self.battery_label = QLabel("unknown")
        self.firmware_label = QLabel("unknown")
        self.settings_failures_label = QLabel("none")
        self.settings_failures_label.setWordWrap(True)
        self.profiles_box = QComboBox()
        self.calibrating_label = QLabel("no")
        self.refresh_button = QPushButton("Refresh")
        self.release_button = QPushButton("Release generated outputs")

        form = QFormLayout()
        form.addRow("Service", self.connection_label)
        form.addRow("Mapping status", self.status_label)
        form.addRow("Transport", self.transport_label)
        form.addRow("Generation", self.generation_label)
        form.addRow("Configuration revision", self.revision_label)
        form.addRow("Profile", self.profiles_box)
        form.addRow("Hardware error", self.error_label)
        form.addRow("Calibrating", self.calibrating_label)
        form.addRow("Observed DPI", self.observed_dpi_label)
        form.addRow("Scroll mode", self.scroll_mode_label)
        form.addRow("Poll rate", self.poll_rate_label)
        form.addRow("Battery", self.battery_label)
        form.addRow("Firmware", self.firmware_label)
        form.addRow("Setting failures", self.settings_failures_label)

        actions = QHBoxLayout()
        actions.addWidget(self.refresh_button)
        actions.addWidget(self.release_button)
        self.calibrate_button = QPushButton("Toggle calibration")
        actions.addWidget(self.calibrate_button)

        column = QFormLayout()
        column.addRow(form)
        column.addRow(actions)
        self.setLayout(column)

        self.refresh_button.clicked.connect(lambda: self._run(self.presenter.refresh))
        self.release_button.clicked.connect(lambda: self._run(self.presenter.release_all))
        self.calibrate_button.clicked.connect(self._toggle_calibration)
        self.profiles_box.currentTextChanged.connect(self._profile_selected)

    def _toggle_calibration(self) -> None:
        snapshot = self.model.snapshot
        active = snapshot is not None and snapshot.calibrating
        call = self.presenter.end_calibration if active else self.presenter.begin_calibration
        self._run(call)

    def _profile_selected(self, profile_id: str) -> None:
        if not self._updating_profiles and profile_id:
            self._run(lambda: self.presenter.select_profile(profile_id))

    def _update_from_model(self) -> None:
        connection = self.model.connection
        self.connection_label.setText(
            "online" if connection.reachable else f"offline: {connection.detail}"
        )
        snapshot = self.model.snapshot
        self.status_label.setText(snapshot.status if snapshot else "unknown")
        self.transport_label.setText(
            snapshot.transport if snapshot and snapshot.transport else "none"
        )
        self.generation_label.setText(str(snapshot.generation) if snapshot else "unknown")
        self.calibrating_label.setText("yes" if snapshot and snapshot.calibrating else "no")
        self.error_label.setText(snapshot.error if snapshot and snapshot.error else "none")
        observed = snapshot.observed if snapshot else None
        dpi = observed.dpi if observed else None
        self.observed_dpi_label.setText(
            f"{dpi[0]}x{dpi[1]} (stage {observed.active_dpi_stage})"
            if dpi and observed
            else "unknown"
        )
        self.scroll_mode_label.setText(
            observed.scroll_mode if observed and observed.scroll_mode else "unknown"
        )
        self.poll_rate_label.setText(
            f"{observed.poll_rate} Hz" if observed and observed.poll_rate else "unknown"
        )
        if observed and observed.battery_percent is not None:
            charging = " charging" if observed.charging else ""
            self.battery_label.setText(f"{observed.battery_percent:.0f}%{charging}")
        else:
            self.battery_label.setText("unknown")
        self.firmware_label.setText(
            observed.firmware_version if observed and observed.firmware_version else "unknown"
        )
        failures = observed.settings_failures if observed else ()
        self.settings_failures_label.setText("; ".join(failures) if failures else "none")
        revision = self.model.configuration_revision
        self.revision_label.setText(str(revision) if revision is not None else "unknown")
        self._update_profiles()

    def _update_profiles(self) -> None:
        document = self.model.configuration_document
        if document is None:
            return
        try:
            profiles = [name for name, _ in parse_toml(document).profiles]
        except Exception:
            logger.warning("could not parse profile list", exc_info=True)
            return
        current = self.profiles_box.currentText()
        self._updating_profiles = True
        try:
            self.profiles_box.clear()
            self.profiles_box.addItems(profiles)
            if profiles and current in profiles:
                self.profiles_box.setCurrentText(current)
        finally:
            self._updating_profiles = False
