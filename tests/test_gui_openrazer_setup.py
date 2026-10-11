import os
from collections.abc import Iterator
from typing import cast
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui_support import make_presenter, sync_run
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication

from naga_control.gui.models import ServiceSnapshotView
from naga_control.gui.overview_page import OverviewPage
from naga_control.gui.profile_mode_view import device_mode_view


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    yield cast(QApplication, QApplication.instance() or QApplication([]))


@pytest.mark.parametrize(
    ("code", "title", "readiness"),
    [
        (
            "openrazer_not_installed",
            "OpenRazer not installed",
            "Not ready (OpenRazer not installed)",
        ),
        (
            "prerequisite_unavailable",
            "OpenRazer client needs repair",
            "Not ready (OpenRazer client needs repair)",
        ),
    ],
)
def test_setup_notice_is_visible_without_diagnostics_and_clears_on_recovery(
    qapp: QApplication, code: str, title: str, readiness: str
) -> None:
    presenter, model, client = make_presenter("")
    page = OverviewPage(presenter, model, sync_run)
    page.show()
    model.apply_snapshot(
        ServiceSnapshotView(
            "unavailable",
            1,
            "hyperspeed",
            "client unavailable",
            mode_error="device mode unavailable: hardware is not available",
            error_code=code,
        )
    )
    qapp.processEvents()

    assert page.openrazer_setup.isVisible()
    assert page.openrazer_setup.title() == title
    assert page.openrazer_guide_button.isVisible()
    assert page.diagnostics_widget.isHidden()
    assert page.status_label.text() == readiness
    assert device_mode_view(model).remapping == readiness
    assert page.error_label.text() == "client unavailable"
    assert "AppImage installs Naga Control only" in page.openrazer_help_label.text()
    assert "No packages are installed automatically" in page.openrazer_help_label.text()
    assert not client.applied

    model.mark_unreachable("disconnected")
    qapp.processEvents()
    assert page.openrazer_setup.isHidden()
    assert page.status_label.text() == "Unknown (service offline)"

    model.apply_snapshot(
        ServiceSnapshotView(
            "available",
            2,
            "hyperspeed",
            None,
            desired_mode="software",
            observed_mode="software",
            mode_ready=True,
        )
    )
    qapp.processEvents()
    assert page.openrazer_setup.isHidden()
    assert page.status_label.text() == "Active (software mode verified)"
    assert page.error_label.text() == "none"
    page.close()


@pytest.mark.parametrize("code", [None, "backend_unavailable", "device_unavailable", "future"])
def test_other_errors_do_not_claim_openrazer_is_not_installed(
    qapp: QApplication, code: str | None
) -> None:
    presenter, model, _client = make_presenter("")
    model.apply_snapshot(ServiceSnapshotView("unavailable", 1, "wired", "boom", error_code=code))
    page = OverviewPage(presenter, model, sync_run)
    page.show()
    qapp.processEvents()
    assert page.openrazer_setup.isHidden()
    assert "OpenRazer not installed" not in page.status_label.text()
    assert page.error_label.text() == "boom"
    page.close()


def test_guide_button_only_opens_documentation(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    opener = Mock(return_value=True)
    monkeypatch.setattr(QDesktopServices, "openUrl", opener)
    presenter, model, client = make_presenter("")
    model.apply_snapshot(
        ServiceSnapshotView(
            "unavailable", 1, "wired", "missing", error_code="openrazer_not_installed"
        )
    )
    page = OverviewPage(presenter, model, sync_run)
    page.openrazer_guide_button.click()
    opener.assert_called_once_with(
        QUrl(
            "https://github.com/Rainexn0b/naga-control/blob/main/docs/release-notes.md#required-openrazer"
        )
    )
    assert not client.applied
