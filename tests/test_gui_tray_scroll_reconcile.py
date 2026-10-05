"""Tray writes reconcile only Scroll drafts, using fake IPC and offscreen Qt."""

import json
import os
from collections.abc import Iterator
from dataclasses import replace
from typing import Any, cast
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui_support import FakeClient, opened, sync_run
from PySide6.QtWidgets import QApplication, QMessageBox

from naga_control.config import dump_toml, parse_toml
from naga_control.domain.defaults import default_configuration
from naga_control.gui.app import MainWindow
from naga_control.gui.models import ServiceModel
from naga_control.gui.presenter import GuiPresenter
from naga_control.gui.tray_icon import TrayIcon
from naga_control.ipc.client import InvalidConfigurationError, StaleRevisionError


class ScrollClient(FakeClient):
    def __init__(self) -> None:
        super().__init__(dump_toml(default_configuration()))
        self.snapshot: dict[str, Any] = {
            "status": "available",
            "generation": 9,
            "transport": "hyperspeed",
            "error": None,
            "observed": {
                "scroll_mode": "tactile",
                "scroll_acceleration": False,
                "scroll_smart_reel": False,
            },
        }

    async def snapshot_document(self) -> str:
        return json.dumps(self.snapshot)

    async def apply_configuration(self, expected_revision: int, document: str) -> int:
        self.applied.append((expected_revision, document))
        current = parse_toml(self.document)
        assert expected_revision == current.revision
        assert parse_toml(document).revision == current.revision + 1
        self.document = document
        return current.revision + 1


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])
    yield cast(QApplication, app)


@pytest.fixture
def window(qapp: QApplication) -> Iterator[tuple[MainWindow, ScrollClient]]:
    client = ScrollClient()
    model = ServiceModel()
    presenter = GuiPresenter(model, open_client=lambda: opened(client))
    widget = MainWindow(presenter, model, sync_run)
    widget._poll_timer.stop()  # pyright: ignore[reportPrivateUsage]
    sync_run(presenter.refresh)
    qapp.processEvents()
    yield widget, client
    widget.deleteLater()
    qapp.processEvents()


def _tray(widget: MainWindow) -> TrayIcon:
    tray = widget._tray  # pyright: ignore[reportPrivateUsage]
    assert tray is not None
    return tray


def _draft_all(widget: MainWindow) -> None:
    widget.settings.scroll_section.mode_box.setCurrentText("free_spin")
    widget.settings.dpi.rows[0].x_spin.setValue(2300)
    widget.settings.lighting.rows[0].brightness_spin.setValue(42)
    assert widget.settings.scroll_section.has_unsaved_changes()
    assert widget.settings.dpi.has_unsaved_changes()
    assert widget.settings.lighting.has_unsaved_changes()


@pytest.mark.parametrize(
    ("failure", "answer"),
    [
        ("stale", QMessageBox.StandardButton.Yes),
        ("offline", QMessageBox.StandardButton.Yes),
        ("invalid", QMessageBox.StandardButton.Yes),
        ("cancel", QMessageBox.StandardButton.No),
    ],
)
def test_failed_or_canceled_tray_write_retains_every_draft(
    qapp: QApplication,
    window: tuple[MainWindow, ScrollClient],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    answer: QMessageBox.StandardButton,
) -> None:
    widget, client = window
    _draft_all(widget)
    before = client.document
    question = Mock(return_value=answer)
    monkeypatch.setattr(QMessageBox, "question", question)

    async def reject(expected_revision: int, document: str) -> int:
        client.applied.append((expected_revision, document))
        if failure == "stale":
            current = parse_toml(client.document)
            client.document = dump_toml(replace(current, revision=current.revision + 1))
            raise StaleRevisionError("another editor saved")
        if failure == "invalid":
            raise InvalidConfigurationError("invalid scroll")
        raise ConnectionError("service disconnected")

    monkeypatch.setattr(client, "apply_configuration", reject)
    _tray(widget).scroll_actions["precision_tactile"].trigger()
    qapp.processEvents()
    question.assert_called_once()
    assert question.call_args.args[1] == "Unsaved scroll changes"
    assert len(client.applied) == (0 if failure == "cancel" else 1)
    assert client.document == (
        dump_toml(replace(parse_toml(before), revision=parse_toml(before).revision + 1))
        if failure == "stale"
        else before
    )
    assert widget.settings.scroll_section.mode_box.currentText() == "free_spin"
    assert widget.settings.scroll_section.has_unsaved_changes()
    assert widget.settings.dpi.rows[0].x_spin.value() == 2300
    assert widget.settings.lighting.rows[0].brightness_spin.value() == 42
    assert widget.settings.dpi.has_unsaved_changes()
    assert widget.settings.lighting.has_unsaved_changes()
    assert widget.settings.has_unsaved_changes()
    assert _tray(widget).scroll_actions["tactile"].isChecked()
    if failure == "offline":
        assert not widget.model.connection.reachable
    else:
        assert widget.model.connection.reachable


def test_success_rebases_only_scroll_and_later_settings_apply_keeps_tray_value(
    qapp: QApplication,
    window: tuple[MainWindow, ScrollClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    widget, client = window
    _draft_all(widget)
    question = Mock(return_value=QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "question", question)
    before = parse_toml(client.document)
    _tray(widget).scroll_actions["precision_tactile"].trigger()
    qapp.processEvents()

    question.assert_called_once()
    assert len(client.applied) == 1
    saved = parse_toml(client.document)
    assert saved.revision == before.revision + 1
    assert saved.profile(saved.active_profile).scroll.mode == "precision_tactile"
    assert saved.profile(saved.active_profile).dpi == before.profile(before.active_profile).dpi
    assert (
        saved.profile(saved.active_profile).lighting
        == before.profile(before.active_profile).lighting
    )
    assert not widget.settings.scroll_section.has_unsaved_changes()
    assert widget.settings.scroll_section.mode_box.currentText() == "precision_tactile"
    assert widget.settings.dpi.has_unsaved_changes()
    assert widget.settings.lighting.has_unsaved_changes()
    assert widget.settings.has_unsaved_changes()

    widget.settings.apply_button.click()
    qapp.processEvents()
    assert len(client.applied) == 2
    assert client.applied[1][0] == saved.revision
    after = parse_toml(client.document)
    profile = after.profile(after.active_profile)
    assert after.revision == saved.revision + 1
    assert profile.scroll == saved.profile(saved.active_profile).scroll
    assert profile.dpi.stages[0].x == 2300
    assert profile.lighting.thumb_grid.brightness == 42
    assert not widget.settings.has_unsaved_changes()


def test_success_refreshes_observed_and_profile_failures_on_finished_worker(
    qapp: QApplication,
    window: tuple[MainWindow, ScrollClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    widget, client = window
    tray = _tray(widget)
    assert tray.observed_scroll_action.text() == "Observed mode: Tactile"
    original_apply = client.apply_configuration

    async def applied_with_new_snapshot(expected_revision: int, document: str) -> int:
        revision = await original_apply(expected_revision, document)
        client.snapshot["observed"] = {
            "scroll_mode": "free_spin",
            "scroll_acceleration": True,
            "scroll_smart_reel": True,
        }
        client.snapshot["settings_failures"] = ["profile: device asleep", "dpi: timeout"]
        return revision

    monkeypatch.setattr(client, "apply_configuration", applied_with_new_snapshot)
    tray.scroll_actions["precision_tactile"].trigger()
    qapp.processEvents()
    assert len(client.applied) == 1
    assert tray.scroll_actions["precision_tactile"].isChecked()
    assert tray.observed_scroll_action.text() == "Observed mode: Free spin"
    assert "acceleration on, Smart Reel on" in tray.observed_scroll_action.toolTip()
    assert tray.scroll_failure_action.isVisible()
    assert "profile: device asleep" in tray.scroll_failure_action.text()
    assert "dpi: timeout" not in tray.scroll_failure_action.text()


@pytest.mark.parametrize("status", ["offline", "unavailable", "absent"])
def test_non_available_snapshot_never_claims_observed_hardware(
    qapp: QApplication, window: tuple[MainWindow, ScrollClient], status: str
) -> None:
    widget, client = window
    tray = _tray(widget)
    client.snapshot["status"] = status
    sync_run(widget.presenter.refresh)
    qapp.processEvents()
    tray.scroll_menu.aboutToShow.emit()
    assert tray.scroll_actions["tactile"].isChecked()
    assert tray.observed_scroll_action.text() == "Observed mode: unknown"
    assert "acceleration unknown, Smart Reel unknown" in tray.observed_scroll_action.toolTip()
    assert tray.scroll_failure_action.isVisible()
    assert status in tray.scroll_failure_action.text()


def test_disconnected_service_does_not_show_cached_observation(
    qapp: QApplication, window: tuple[MainWindow, ScrollClient]
) -> None:
    widget, client = window
    tray = _tray(widget)
    client.snapshot["observed"] = {"scroll_mode": "free_spin", "scroll_smart_reel": True}
    sync_run(widget.presenter.refresh)
    qapp.processEvents()
    assert tray.observed_scroll_action.text() == "Observed mode: Free spin"

    widget.model.mark_unreachable("service disconnected")
    qapp.processEvents()
    assert tray.scroll_actions["tactile"].isChecked()
    assert tray.observed_scroll_action.text() == "Observed mode: unknown"
    assert "Smart Reel unknown" in tray.observed_scroll_action.toolTip()
    assert not tray.scroll_menu.isEnabled()
