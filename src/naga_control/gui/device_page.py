"""Device tab combining connection information, power, and profile management."""

from collections.abc import Awaitable, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QWidget

from naga_control.gui.application_panel import ApplicationPanel
from naga_control.gui.autostart import AutostartStore
from naga_control.gui.models import ServiceModel
from naga_control.gui.overview_page import OverviewPage
from naga_control.gui.power_page import PowerPage
from naga_control.gui.presenter import GuiPresenter
from naga_control.gui.profile_mode_view import SOFTWARE_PROFILE_HELP
from naga_control.gui.profiles_page import ProfilesPage
from naga_control.gui.service_action_controller import ServiceActionGuard
from naga_control.gui.service_restart import RestartResult
from naga_control.gui.two_columns import TwoColumns
from naga_control.gui.version_panel import VersionPanel
from naga_control.gui.worker import Runner


class DevicePage(TwoColumns):
    """Power retains its own apply action and participates in the shell's guard."""

    def __init__(
        self,
        presenter: GuiPresenter,
        model: ServiceModel,
        run: Runner,
        *,
        autostart: AutostartStore | None = None,
        restarter: Callable[[], Awaitable[RestartResult]] | None = None,
        application_confirm: Callable[[], bool] | None = None,
        restart_guard: ServiceActionGuard | None = None,
    ) -> None:
        self.overview = OverviewPage(presenter, model, run)
        self.power = PowerPage(presenter, model, run)
        self.profiles = ProfilesPage(presenter, model, run)
        self.power.header_widget.hide()
        self.power.apply_button.setText("Apply power")

        connection = QGroupBox("Connection and Battery")
        QVBoxLayout(connection).addWidget(self.overview)
        power = QGroupBox("Power")
        QVBoxLayout(power).addWidget(self.power)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        left_layout.addWidget(connection)
        left_layout.addWidget(power)

        profiles = QGroupBox("Software profiles")
        profiles.setToolTip(SOFTWARE_PROFILE_HELP)
        QVBoxLayout(profiles).addWidget(self.profiles)
        self.updates = VersionPanel(run)
        updates = QGroupBox("Updates")
        QVBoxLayout(updates).addWidget(self.updates)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        right_layout.addWidget(profiles)
        right_layout.addWidget(updates)
        self.application: ApplicationPanel | None = None
        if autostart is not None or restarter is not None:
            self.application = ApplicationPanel(
                presenter,
                model,
                run,
                autostart=autostart,
                restarter=restarter,
                confirm=application_confirm,
                restart_guard=restart_guard,
            )
            application_box = QGroupBox("Application")
            application_box.setToolTip(
                "Login startup and background service controls. "
                "The mapping service setting is unchanged."
            )
            QVBoxLayout(application_box).addWidget(self.application)
            right_layout.addWidget(application_box)
        super().__init__(left, right)

    def has_unsaved_changes(self) -> bool:
        return self.power.has_unsaved_changes() or self.profiles.has_unsaved_changes()

    def discard_changes(self) -> None:
        self.power.discard_changes()
        self.profiles.discard_changes()
