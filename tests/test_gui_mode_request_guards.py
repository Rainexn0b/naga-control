"""Timing guards for pending saves and deferred mode changes (fake service only)."""

import asyncio
import os
from collections.abc import Iterator
from typing import cast
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui_support import opened
from gui_tray_profiles_fakes import SelectingClient
from PySide6.QtWidgets import QApplication, QMessageBox

from naga_control.gui.app import MainWindow
from naga_control.gui.models import ServiceModel, ServiceSnapshotView
from naga_control.gui.presenter import GuiPresenter
from naga_control.gui.worker import CoroFactory


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])
    yield cast(QApplication, app)


def _firmware_snapshot() -> ServiceSnapshotView:
    return ServiceSnapshotView(
        "available",
        2,
        "hyperspeed",
        None,
        desired_mode="firmware",
        observed_mode="firmware",
        mode_ready=True,
    )


def test_activation_blocked_while_config_save_pending(qapp: QApplication) -> None:
    client = SelectingClient()
    model = ServiceModel()
    presenter = GuiPresenter(model, open_client=lambda: opened(client))
    jobs: list[CoroFactory] = []
    widget = MainWindow(presenter, model, jobs.append)
    widget._poll_timer.stop()  # pyright: ignore[reportPrivateUsage]
    try:
        asyncio.run(presenter.refresh())
        qapp.processEvents()
        page = widget.device.profiles
        model.set_apply_status("applying…")
        qapp.processEvents()
        page.profiles_box.setCurrentIndex(page.profiles_box.findData("second"))
        qapp.processEvents()
        assert not page.activate_button.isEnabled()
        assert "pending" in page.activate_button.toolTip().lower()
        assert not page.new_button.isEnabled()
        assert not page.apply_plate_button.isEnabled()
        widget._request_profile("second")  # pyright: ignore[reportPrivateUsage]
        qapp.processEvents()
        assert jobs == []
        assert client.selected == []
        before = client.document
        page.apply_document(before)  # pyright: ignore[reportPrivateUsage]
        assert jobs == []
        assert client.document == before
    finally:
        widget.deleteLater()
        qapp.processEvents()


async def test_deferred_profile_blocked_after_mode_change_preserves_drafts(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = SelectingClient()
    model = ServiceModel()
    presenter = GuiPresenter(model, open_client=lambda: opened(client))
    jobs: list[CoroFactory] = []
    widget = MainWindow(presenter, model, jobs.append)
    widget._poll_timer.stop()  # pyright: ignore[reportPrivateUsage]
    try:
        await presenter.refresh()
        qapp.processEvents()
        page = widget.device.profiles
        tray = widget._tray  # pyright: ignore[reportPrivateUsage]
        assert tray is not None
        monkeypatch.setattr(
            QMessageBox, "question", Mock(return_value=QMessageBox.StandardButton.Yes)
        )
        widget.settings.dpi.rows[0].x_spin.setValue(2300)
        page.profiles_box.setCurrentIndex(page.profiles_box.findData("first"))
        page.plate_box.setCurrentIndex(page.plate_box.findData(6))
        assert page.has_unsaved_changes()
        page.profiles_box.setCurrentIndex(page.profiles_box.findData("second"))
        page.activate_button.click()
        qapp.processEvents()
        assert len(jobs) == 1
        assert not widget.device.isEnabled()
        model.apply_snapshot(_firmware_snapshot())
        qapp.processEvents()
        await jobs.pop()()
        qapp.processEvents()
        assert client.selected == []
        assert model.apply_status == "Profile switch failed"
        assert widget.device.isEnabled()
        assert widget.settings.dpi.rows[0].x_spin.value() == 2300
        assert widget.settings.has_unsaved_changes()
        assert page.has_unsaved_changes()
        assert tray.profile_actions["first"].isChecked()
    finally:
        widget.deleteLater()
        qapp.processEvents()


async def test_deferred_scroll_blocked_after_mode_change_preserves_drafts(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gui_tray_scroll_fakes import ScrollClient

    client = ScrollClient()
    model = ServiceModel()
    presenter = GuiPresenter(model, open_client=lambda: opened(client))
    jobs: list[CoroFactory] = []
    widget = MainWindow(presenter, model, jobs.append)
    widget._poll_timer.stop()  # pyright: ignore[reportPrivateUsage]
    try:
        await presenter.refresh()
        qapp.processEvents()
        tray = widget._tray  # pyright: ignore[reportPrivateUsage]
        assert tray is not None
        monkeypatch.setattr(
            QMessageBox, "question", Mock(return_value=QMessageBox.StandardButton.Yes)
        )
        widget.settings.scroll_section.mode_box.setCurrentText("free_spin")
        assert widget.settings.scroll_section.has_unsaved_changes()
        tray.scroll_actions["free_spin"].trigger()
        qapp.processEvents()
        assert len(jobs) == 1
        model.apply_snapshot(_firmware_snapshot())
        qapp.processEvents()
        await jobs.pop()()
        qapp.processEvents()
        assert client.applied == []
        assert "saved" not in (model.apply_status or "")
        assert widget.settings.scroll_section.has_unsaved_changes()
        assert tray.scroll_actions["tactile"].isChecked()
        assert widget.device.isEnabled()
    finally:
        widget.deleteLater()
        qapp.processEvents()


def test_profile_blocked_while_scroll_pending_even_when_enabled(qapp: QApplication) -> None:
    from gui_tray_profiles_fakes import SelectingClient as ProfileClient

    from naga_control.gui.tray_icon import TrayIcon

    client = ProfileClient()
    model = ServiceModel()
    presenter = GuiPresenter(model, open_client=lambda: opened(client))
    asyncio.run(presenter.refresh())
    qapp.processEvents()
    select, scroll = Mock(), Mock()
    tray = TrayIcon(
        model,
        toggle_window=Mock(),
        select_profile=select,
        change_scroll=scroll,
        quit_app=Mock(),
    )
    qapp.processEvents()
    assert tray._software_allowed()  # pyright: ignore[reportPrivateUsage]
    assert tray.profile_menu.isEnabled()
    checked_before = [k for k, a in tray.profile_actions.items() if a.isChecked()]
    assert checked_before == ["first"]
    tray.set_scroll_switching(True)
    qapp.processEvents()
    assert not tray.profile_menu.isEnabled()
    tray._profile_requested("second")  # pyright: ignore[reportPrivateUsage]
    qapp.processEvents()
    select.assert_not_called()
    scroll.assert_not_called()
    for action in tray.profile_actions.values():
        action.setEnabled(True)
        action.trigger()
    qapp.processEvents()
    select.assert_not_called()
    scroll.assert_not_called()
    assert [k for k, a in tray.profile_actions.items() if a.isChecked()] == ["first"]
    assert client.selected == []
    tray.deleteLater()
    qapp.processEvents()


@pytest.mark.parametrize("variant", ["firmware", "not-ready", "offline"])
async def test_profile_post_confirmation_mutation_blocks_queue(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, variant: str
) -> None:
    client = SelectingClient()
    model = ServiceModel()
    presenter = GuiPresenter(model, open_client=lambda: opened(client))
    jobs: list[CoroFactory] = []
    widget = MainWindow(presenter, model, jobs.append)
    widget._poll_timer.stop()  # pyright: ignore[reportPrivateUsage]
    try:
        await presenter.refresh()
        qapp.processEvents()
        page = widget.device.profiles
        tray = widget._tray  # pyright: ignore[reportPrivateUsage]
        assert tray is not None
        assert tray._software_allowed()  # pyright: ignore[reportPrivateUsage]
        widget.settings.dpi.rows[0].x_spin.setValue(2300)
        page.profiles_box.setCurrentIndex(page.profiles_box.findData("first"))
        page.plate_box.setCurrentIndex(page.plate_box.findData(6))
        assert page.has_unsaved_changes()

        def mutate_and_yes(*args: object, **kwargs: object) -> QMessageBox.StandardButton:
            if variant == "firmware":
                model.apply_snapshot(_firmware_snapshot())
            elif variant == "not-ready":
                model.apply_snapshot(
                    ServiceSnapshotView(
                        "available",
                        3,
                        "hyperspeed",
                        None,
                        desired_mode="software",
                        observed_mode="software",
                        mode_ready=False,
                    )
                )
            else:
                model.mark_unreachable("lost")
            return QMessageBox.StandardButton.Yes

        monkeypatch.setattr(QMessageBox, "question", mutate_and_yes)
        page.profiles_box.setCurrentIndex(page.profiles_box.findData("second"))
        page.activate_button.click()
        qapp.processEvents()
        assert jobs == []
        assert client.selected == []
        assert widget.settings.dpi.rows[0].x_spin.value() == 2300
        assert widget.settings.has_unsaved_changes()
        assert page.has_unsaved_changes()
        assert tray.profile_actions["first"].isChecked()
    finally:
        widget.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("variant", ["firmware", "not-ready", "offline"])
async def test_scroll_post_confirmation_mutation_blocks_queue(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, variant: str
) -> None:
    from gui_tray_scroll_fakes import ScrollClient

    client = ScrollClient()
    model = ServiceModel()
    presenter = GuiPresenter(model, open_client=lambda: opened(client))
    jobs: list[CoroFactory] = []
    widget = MainWindow(presenter, model, jobs.append)
    widget._poll_timer.stop()  # pyright: ignore[reportPrivateUsage]
    try:
        await presenter.refresh()
        qapp.processEvents()
        tray = widget._tray  # pyright: ignore[reportPrivateUsage]
        assert tray is not None
        assert tray._software_allowed()  # pyright: ignore[reportPrivateUsage]
        widget.settings.scroll_section.mode_box.setCurrentText("free_spin")
        widget.settings.dpi.rows[0].x_spin.setValue(2300)
        assert widget.settings.scroll_section.has_unsaved_changes()

        def mutate_and_yes(*args: object, **kwargs: object) -> QMessageBox.StandardButton:
            if variant == "firmware":
                model.apply_snapshot(_firmware_snapshot())
            elif variant == "not-ready":
                model.apply_snapshot(
                    ServiceSnapshotView(
                        "available",
                        3,
                        "hyperspeed",
                        None,
                        desired_mode="software",
                        observed_mode="software",
                        mode_ready=False,
                    )
                )
            else:
                model.mark_unreachable("lost")
            return QMessageBox.StandardButton.Yes

        monkeypatch.setattr(QMessageBox, "question", mutate_and_yes)
        tray.scroll_actions["free_spin"].trigger()
        qapp.processEvents()
        assert jobs == []
        assert client.applied == []
        assert widget.settings.scroll_section.has_unsaved_changes()
        assert widget.settings.scroll_section.mode_box.currentText() == "free_spin"
        assert widget.settings.dpi.rows[0].x_spin.value() == 2300
        assert tray.scroll_actions["tactile"].isChecked()
    finally:
        widget.deleteLater()
        qapp.processEvents()
