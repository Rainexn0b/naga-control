"""Connection summary with optional service diagnostics and safe actions."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFormLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from naga_control.gui.models import ServiceModel
from naga_control.gui.presenter import GuiPresenter
from naga_control.gui.profile_mode_view import DEVICE_MODE_HELP, device_mode_view
from naga_control.gui.worker import Runner


class OverviewPage(QWidget):
    """Show service state; never import evdev or OpenRazer here."""

    model_changed = Signal()

    def __init__(self, presenter: GuiPresenter, model: ServiceModel, run: Runner) -> None:
        super().__init__()
        self.presenter = presenter
        self.model = model
        self._run = run

        self.model.add_listener(self.model_changed.emit)
        self.model_changed.connect(self._update_from_model, Qt.ConnectionType.QueuedConnection)

        self.connection_label = QLabel("connecting…")
        self.status_label = QLabel("unknown")
        self.transport_label = QLabel("unknown")
        self.generation_label = QLabel("unknown")
        self.revision_label = QLabel("unknown")
        self.error_label = QLabel("none")
        self.error_label.setWordWrap(True)
        self.mode_label = QLabel("unknown")
        self.mode_label.setWordWrap(True)
        self.requested_mode_label = QLabel("unknown")
        self.requested_mode_label.setWordWrap(True)
        for label in (self.mode_label, self.requested_mode_label, self.status_label):
            label.setToolTip(DEVICE_MODE_HELP)
        self.status_label.setWordWrap(True)
        self.mode_error_label = QLabel("none")
        self.mode_error_label.setWordWrap(True)
        self.observed_dpi_label = QLabel("unknown")
        self.scroll_mode_label = QLabel("unknown")
        self.poll_rate_label = QLabel("unknown")
        self.battery_label = QLabel("unknown")
        self.charging_label = QLabel("unknown")
        self.firmware_label = QLabel("unknown")
        self.settings_failures_label = QLabel("none")
        self.settings_failures_label.setWordWrap(True)
        self.calibrating_label = QLabel("no")
        self.refresh_button = QPushButton("Refresh")
        self.release_button = QPushButton("Release generated outputs")

        form = QFormLayout()
        form.addRow("Service", self.connection_label)
        form.addRow("Software remapping", self.status_label)
        form.addRow("Requested device mode", self.requested_mode_label)
        form.addRow("Observed device mode", self.mode_label)
        form.addRow("Mode error", self.mode_error_label)
        form.addRow("Transport", self.transport_label)
        form.addRow("Hardware error", self.error_label)
        form.addRow("Observed DPI", self.observed_dpi_label)
        form.addRow("Scroll wheel mode", self.scroll_mode_label)
        form.addRow("Poll rate", self.poll_rate_label)
        form.addRow("Battery", self.battery_label)
        form.addRow("Charging", self.charging_label)
        form.addRow("Firmware", self.firmware_label)
        form.addRow("Setting failures", self.settings_failures_label)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        self.diagnostics_button = QPushButton("Show diagnostics")
        self.diagnostics_button.setCheckable(True)
        self.diagnostics_widget = QWidget()
        diagnostics = QFormLayout()
        diagnostics.addRow("Generation", self.generation_label)
        diagnostics.addRow("Configuration revision", self.revision_label)
        diagnostics.addRow("Calibrating", self.calibrating_label)
        diagnostics.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        actions = QVBoxLayout()
        actions.addWidget(self.refresh_button)
        actions.addWidget(self.release_button)
        self.calibrate_button = QPushButton("Toggle calibration")
        actions.addWidget(self.calibrate_button)

        diagnostics_column = QVBoxLayout(self.diagnostics_widget)
        diagnostics_column.setContentsMargins(0, 0, 0, 0)
        diagnostics_column.addLayout(diagnostics)
        diagnostics_column.addLayout(actions)
        self.diagnostics_widget.hide()
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setAlignment(Qt.AlignmentFlag.AlignTop)
        column.addLayout(form)
        column.addWidget(self.diagnostics_button)
        column.addWidget(self.diagnostics_widget)

        self.refresh_button.clicked.connect(lambda: self._run(self.presenter.refresh))
        self.release_button.clicked.connect(lambda: self._run(self.presenter.release_all))
        self.calibrate_button.clicked.connect(self._toggle_calibration)
        self.diagnostics_button.toggled.connect(self._show_diagnostics)
        self._update_from_model()

    def _show_diagnostics(self, expanded: bool) -> None:
        self.diagnostics_widget.setVisible(expanded)
        self.diagnostics_button.setText("Hide diagnostics" if expanded else "Show diagnostics")

    def _toggle_calibration(self) -> None:
        snapshot = self.model.snapshot
        active = snapshot is not None and snapshot.calibrating
        call = self.presenter.end_calibration if active else self.presenter.begin_calibration
        self._run(call)

    def _update_from_model(self) -> None:
        connection = self.model.connection
        self.connection_label.setText(
            "online" if connection.reachable else f"offline: {connection.detail}"
        )
        snapshot = self.model.snapshot
        mode = device_mode_view(self.model)
        self.status_label.setText(mode.remapping)
        self.requested_mode_label.setText(mode.requested)
        self.mode_label.setText(mode.observed)
        self.mode_error_label.setText(mode.error or "none")
        self.calibrate_button.setEnabled(not (snapshot and snapshot.desired_mode == "firmware"))
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
        self.charging_label.setText(
            ("yes" if observed.charging else "no")
            if observed and observed.charging is not None
            else "unknown"
        )
        self.firmware_label.setText(
            observed.firmware_version if observed and observed.firmware_version else "unknown"
        )
        failures = observed.settings_failures if observed else ()
        self.settings_failures_label.setText("; ".join(failures) if failures else "none")
        revision = self.model.configuration_revision
        self.revision_label.setText(str(revision) if revision is not None else "unknown")
