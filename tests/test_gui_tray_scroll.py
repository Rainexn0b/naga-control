"""Offscreen tray scroll shortcuts against a fake service, never a mouse."""

import asyncio
import os
from dataclasses import replace
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui_support import opened, sync_run
from gui_tray_scroll_fakes import GatedScrollClient, ScrollClient
from gui_tray_scroll_fakes import qapp as qapp
from gui_tray_scroll_fakes import window as window
from PySide6.QtWidgets import QApplication, QMessageBox

from naga_control.config import dump_toml, parse_toml
from naga_control.domain.profiles import ScrollMode, ScrollSettings
from naga_control.gui.app import MainWindow
from naga_control.gui.models import ServiceModel
from naga_control.gui.presenter import GuiPresenter
from naga_control.gui.tray_icon import TrayIcon
from naga_control.gui.worker import CoroFactory


def _tray(widget: MainWindow) -> TrayIcon:
    tray = widget._tray  # pyright: ignore[reportPrivateUsage]
    assert tray is not None
    return tray


def _checked(tray: TrayIcon) -> list[ScrollMode]:
    return [mode for mode, action in tray.scroll_actions.items() if action.isChecked()]


def test_saved_checks_and_observation_are_independent_and_read_only(
    qapp: QApplication, window: tuple[MainWindow, ScrollClient]
) -> None:
    widget, client = window
    tray = _tray(widget)
    assert tray.scroll_menu.menuAction() in tray.software_menu.actions()
    assert tray.software_menu.menuAction() in tray.menu.actions()
    assert tray.onboard_menu.menuAction() in tray.menu.actions()
    assert tray.scroll_group.isExclusive()
    assert [action.text() for action in tray.scroll_actions.values()] == [
        "Tactile",
        "Free spin",
        "Precision tactile",
    ]
    assert all(action.isCheckable() for action in tray.scroll_actions.values())
    assert _checked(tray) == ["tactile"]
    assert not tray.acceleration_action.isChecked()
    assert not tray.smart_reel_action.isChecked()
    assert tray.observed_scroll_action.text() == "Observed mode: unknown"
    assert "acceleration unknown, Smart Reel unknown" in tray.observed_scroll_action.toolTip()
    assert not tray.scroll_failure_action.isVisible()

    before = client.document
    client.snapshot["observed"] = {
        "scroll_mode": "free_spin",
        "scroll_acceleration": True,
        "scroll_smart_reel": False,
    }
    client.snapshot["settings_failures"] = ["dpi: failed", "scroll_mode: timeout"]
    sync_run(widget.presenter.refresh)
    qapp.processEvents()
    tray.menu.aboutToShow.emit()
    tray.scroll_menu.aboutToShow.emit()
    assert _checked(tray) == ["tactile"]
    assert tray.observed_scroll_action.text() == "Observed mode: Free spin"
    assert "acceleration on, Smart Reel off" in tray.observed_scroll_action.toolTip()
    assert tray.scroll_failure_action.isVisible()
    assert "scroll_mode: timeout" in tray.scroll_failure_action.text()
    assert "dpi: failed" not in tray.scroll_failure_action.text()
    assert client.document == before
    assert client.applied == []


@pytest.mark.parametrize("mode", ["tactile", "free_spin", "precision_tactile"])
def test_each_mode_saves_only_scroll_with_one_revision(
    qapp: QApplication, window: tuple[MainWindow, ScrollClient], mode: ScrollMode
) -> None:
    widget, client = window
    tray = _tray(widget)
    before = parse_toml(client.document)
    if mode == "tactile":
        # Make tactile a real change rather than a no-op.
        profiles = dict(before.profiles)
        profiles["first"] = replace(
            profiles["first"], scroll=ScrollSettings("free_spin", False, False)
        )
        client.document = dump_toml(replace(before, profiles=tuple(profiles.items())))
        sync_run(widget.presenter.refresh)
        qapp.processEvents()
        before = parse_toml(client.document)
    tray.scroll_actions[mode].trigger()
    qapp.processEvents()
    assert len(client.applied) == 1
    expected, sent = client.applied[0]
    after = parse_toml(sent)
    assert expected == before.revision
    assert after.revision == before.revision + 1
    profiles = dict(before.profiles)
    profiles["first"] = replace(
        profiles["first"], scroll=replace(profiles["first"].scroll, mode=mode)
    )
    assert after == replace(before, revision=before.revision + 1, profiles=tuple(profiles.items()))
    assert parse_toml(client.document) == after
    assert _checked(tray) == [mode]
    assert widget.model.apply_status is not None
    assert "saved" in widget.model.apply_status
    assert "hardware" in widget.model.apply_status


@pytest.mark.parametrize("flag", ["acceleration", "smart_reel"])
def test_each_toggle_saves_only_its_flag(
    qapp: QApplication, window: tuple[MainWindow, ScrollClient], flag: str
) -> None:
    widget, client = window
    tray = _tray(widget)
    before = parse_toml(client.document)
    action = tray.acceleration_action if flag == "acceleration" else tray.smart_reel_action
    action.trigger()
    qapp.processEvents()
    assert len(client.applied) == 1
    expected, sent = client.applied[0]
    after = parse_toml(sent)
    assert expected == before.revision
    profiles = dict(before.profiles)
    profiles["first"] = replace(
        profiles["first"], scroll=replace(profiles["first"].scroll, **{flag: True})
    )
    assert after == replace(before, revision=before.revision + 1, profiles=tuple(profiles.items()))
    assert action.isChecked()
    assert _checked(tray) == ["tactile"]
    assert not (
        tray.smart_reel_action if flag == "acceleration" else tray.acceleration_action
    ).isChecked()


def test_remote_config_and_profile_switch_resync_without_writes(
    qapp: QApplication, window: tuple[MainWindow, ScrollClient]
) -> None:
    widget, client = window
    tray = _tray(widget)
    before = parse_toml(client.document)
    client.document = dump_toml(
        replace(before, revision=before.revision + 1, active_profile="second")
    )
    sync_run(widget.presenter.refresh)
    qapp.processEvents()
    tray.scroll_menu.aboutToShow.emit()
    assert _checked(tray) == ["precision_tactile"]
    assert tray.acceleration_action.isChecked()
    assert tray.smart_reel_action.isChecked()
    assert client.applied == []
    assert parse_toml(client.document).profile("first") == before.profile("first")


def test_saved_scroll_with_hardware_failure_keeps_desired_and_observed_separate(
    qapp: QApplication, window: tuple[MainWindow, ScrollClient]
) -> None:
    widget, client = window
    tray = _tray(widget)
    tray.scroll_actions["free_spin"].trigger()
    qapp.processEvents()
    client.snapshot["observed"] = {"scroll_mode": "tactile", "scroll_acceleration": False}
    client.snapshot["settings_failures"] = ["scroll_mode: device asleep"]
    sync_run(widget.presenter.refresh)
    qapp.processEvents()
    assert _checked(tray) == ["free_spin"]
    assert tray.observed_scroll_action.text() == "Observed mode: Tactile"
    assert "Smart Reel unknown" in tray.observed_scroll_action.toolTip()
    assert "scroll_mode: device asleep" in tray.scroll_failure_action.text()
    assert "hardware status may update" in (widget.model.apply_status or "")
    assert len(client.applied) == 1


@pytest.mark.parametrize("invalid", [False, True], ids=["offline", "invalid-config"])
def test_unavailable_scroll_menu_ignores_programmatic_requests(
    qapp: QApplication, window: tuple[MainWindow, ScrollClient], invalid: bool
) -> None:
    widget, client = window
    tray = _tray(widget)
    if invalid:
        widget.model.apply_configuration(99, "not valid toml = [")
    else:
        widget.model.mark_unreachable("offline")
    qapp.processEvents()
    assert not tray.scroll_menu.isEnabled()
    tray._scroll_requested(mode="free_spin", acceleration=True, smart_reel=True)  # pyright: ignore[reportPrivateUsage]
    tray.scroll_actions["free_spin"].trigger()
    qapp.processEvents()
    assert client.applied == []
    assert _checked(tray) == ([] if invalid else ["tactile"])
    assert not tray.acceleration_action.isChecked()
    assert not tray.smart_reel_action.isChecked()


@pytest.mark.parametrize("failure", [None, "stale", "offline"])
async def test_pending_guard_and_failure_reconcile(qapp: QApplication, failure: str | None) -> None:
    client = GatedScrollClient(failure)
    model = ServiceModel()
    presenter = GuiPresenter(model, open_client=lambda: opened(client))
    jobs: list[CoroFactory] = []
    widget = MainWindow(presenter, model, jobs.append)
    widget._poll_timer.stop()  # pyright: ignore[reportPrivateUsage]
    task: asyncio.Task[object] | None = None
    try:
        await presenter.refresh()
        qapp.processEvents()
        tray = _tray(widget)
        original = parse_toml(client.document)
        tray.scroll_actions["free_spin"].trigger()
        assert len(jobs) == 1
        assert not tray.scroll_menu.isEnabled()
        assert not tray.profile_menu.isEnabled()
        assert not tray.software_menu.isEnabled()
        assert not widget.device.isEnabled()
        assert _checked(tray) == ["tactile"]
        tray.smart_reel_action.trigger()
        tray._scroll_requested(mode="precision_tactile")  # pyright: ignore[reportPrivateUsage]
        tray.profile_actions["second"].trigger()
        widget._request_profile("second")  # pyright: ignore[reportPrivateUsage]
        assert len(jobs) == 1
        assert _checked(tray) == ["tactile"]

        task = asyncio.create_task(jobs.pop()())
        await asyncio.wait_for(client.started.wait(), 5)
        await presenter.refresh()
        qapp.processEvents()
        assert len(client.applied) == 1
        assert client.applied[0][0] == original.revision
        assert not task.done()
        assert not tray.scroll_menu.isEnabled()
        assert not tray.profile_menu.isEnabled()
        assert _checked(tray) == ["tactile"]

        client.finish.set()
        await asyncio.wait_for(task, 5)
        qapp.processEvents()
        assert tray.scroll_menu.isEnabled() == (failure != "offline")
        assert tray.profile_menu.isEnabled() == (failure != "offline")
        assert _checked(tray) == (["free_spin"] if failure is None else ["tactile"])
        assert parse_toml(client.document).active_profile == "first"
        assert not jobs
        if failure is None:
            assert parse_toml(client.document).revision == original.revision + 1
            assert model.apply_status is not None and "saved" in model.apply_status
        else:
            assert model.apply_status is not None and "saved" not in model.apply_status
            assert (
                "retry" in model.apply_status
                if failure == "stale"
                else "unreachable" in model.apply_status
            )
    finally:
        client.finish.set()
        if task is not None:
            await task
        widget.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("answer", [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes])
def test_hidden_scroll_draft_confirmation_only_discards_scroll(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    window: tuple[MainWindow, ScrollClient],
    answer: QMessageBox.StandardButton,
) -> None:
    widget, client = window
    tray = _tray(widget)
    settings = widget.settings
    settings.scroll_section.mode_box.setCurrentText("free_spin")
    settings.dpi.rows[0].x_spin.setValue(2300)
    settings.lighting.rows[0].brightness_spin.setValue(42)
    assert settings.scroll_section.has_unsaved_changes()
    assert settings.dpi.has_unsaved_changes()
    assert settings.lighting.has_unsaved_changes()
    question = Mock(return_value=answer)
    monkeypatch.setattr(QMessageBox, "question", question)
    assert not widget.isVisible()
    tray.scroll_actions["precision_tactile"].trigger()
    qapp.processEvents()
    question.assert_called_once()
    assert question.call_args.args[0] is None
    assert question.call_args.args[1] == "Unsaved scroll changes"
    assert not widget.isVisible()
    assert settings.dpi.rows[0].x_spin.value() == 2300
    assert settings.lighting.rows[0].brightness_spin.value() == 42
    assert settings.dpi.has_unsaved_changes()
    assert settings.lighting.has_unsaved_changes()
    if answer == QMessageBox.StandardButton.No:
        assert settings.scroll_section.has_unsaved_changes()
        assert settings.scroll_section.mode_box.currentText() == "free_spin"
        assert not client.applied
        assert _checked(tray) == ["tactile"]
    else:
        assert not settings.scroll_section.has_unsaved_changes()
        assert settings.scroll_section.mode_box.currentText() == "precision_tactile"
        assert len(client.applied) == 1
        assert _checked(tray) == ["precision_tactile"]
        assert settings.has_unsaved_changes()


def test_unrelated_settings_drafts_do_not_prompt_or_get_saved(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, window: tuple[MainWindow, ScrollClient]
) -> None:
    widget, client = window
    settings = widget.settings
    settings.dpi.rows[0].x_spin.setValue(2300)
    settings.lighting.rows[0].brightness_spin.setValue(42)
    question = Mock()
    monkeypatch.setattr(QMessageBox, "question", question)
    before = parse_toml(client.document)
    _tray(widget).smart_reel_action.trigger()
    qapp.processEvents()
    question.assert_not_called()
    assert len(client.applied) == 1
    assert parse_toml(client.document).profile("first").dpi == before.profile("first").dpi
    assert parse_toml(client.document).profile("first").lighting == before.profile("first").lighting
    assert settings.dpi.has_unsaved_changes()
    assert settings.lighting.has_unsaved_changes()
    assert settings.dpi.rows[0].x_spin.value() == 2300
    assert settings.lighting.rows[0].brightness_spin.value() == 42
