"""Unified dropdown plus Activate ownership, drafts, and narrow layout."""

import json
import os
from collections.abc import Iterator
from dataclasses import replace
from typing import cast
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui_support import FakeClient, make_presenter, sync_run
from PySide6.QtWidgets import QApplication, QMessageBox

from naga_control.config import dump_toml, parse_toml
from naga_control.gui.app import MainWindow
from naga_control.gui.models import ServiceModel, parse_snapshot
from naga_control.gui.presenter import GuiPresenter

VERIFIED = json.dumps(
    {
        "status": "available",
        "generation": 1,
        "transport": "hyperspeed",
        "error": None,
        "desired_mode": "software",
        "observed_mode": "software",
        "mode_ready": True,
        "mode_error": None,
        "calibrating": False,
    }
)


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])
    yield cast(QApplication, app)


def _window(qapp: QApplication) -> tuple[MainWindow, FakeClient, ServiceModel, GuiPresenter]:
    presenter, model, client = make_presenter("")
    widget = MainWindow(presenter, model, sync_run)
    widget._poll_timer.stop()  # pyright: ignore[reportPrivateUsage]
    sync_run(presenter.refresh)
    model.apply_snapshot(parse_snapshot(VERIFIED))
    qapp.processEvents()
    return widget, client, model, presenter


def _page(widget: MainWindow):  # pyright: ignore[reportUnknownParameterType]
    return widget.device.profiles


def _two_profiles(client: FakeClient, widget: MainWindow, qapp: QApplication) -> None:
    base = parse_toml(client.document)
    profile = replace(base.profile(base.active_profile), display_name="Same")
    client.document = dump_toml(
        replace(
            base,
            active_profile="first",
            default_profile="first",
            profiles=(("first", profile), ("second", profile)),
        )
    )
    sync_run(widget.presenter.refresh)
    qapp.processEvents()


def test_single_dropdown_replaces_header_and_list(qapp: QApplication) -> None:
    widget, _client, _model, _presenter = _window(qapp)
    page = _page(widget)
    assert not hasattr(widget, "profiles_box")
    assert not hasattr(widget, "profile_selector_label")
    assert not hasattr(page, "list_widget")
    assert page.profiles_box.count() >= 1
    assert page.active_label.text().startswith("Active:")
    assert page.activate_button.text() == "Activate"
    assert all(
        isinstance(page.profiles_box.itemData(i), str) for i in range(page.profiles_box.count())
    )
    widget.deleteLater()
    qapp.processEvents()


def test_duplicate_names_use_stable_ids_and_management_targets_selected(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, client, _model, _presenter = _window(qapp)
    _two_profiles(client, widget, qapp)
    page = _page(widget)
    assert [page.profiles_box.itemText(i) for i in range(2)] == ["Same (first)", "Same (second)"]
    assert [page.profiles_box.itemData(i) for i in range(2)] == ["first", "second"]
    page.profiles_box.setCurrentIndex(page.profiles_box.findData("second"))
    assert page.active_label.text() == "Active: Same (first)"
    assert widget.settings.profile_id == "first"
    monkeypatch.setattr(page, "_prompt", Mock(return_value="Renamed Second"))
    page.rename_button.click()
    qapp.processEvents()
    after = parse_toml(client.document)
    assert after.profile("second").display_name == "Renamed Second"
    assert after.active_profile == "first"
    assert widget.settings.profile_id == "first"
    widget.deleteLater()
    qapp.processEvents()


def test_active_indicator_follows_service_and_selection_fallback(
    qapp: QApplication,
) -> None:
    widget, client, _model, _presenter = _window(qapp)
    _two_profiles(client, widget, qapp)
    page = _page(widget)
    page.profiles_box.setCurrentIndex(page.profiles_box.findData("second"))
    qapp.processEvents()
    assert page.profiles_box.currentData() == "second"
    config = parse_toml(client.document)
    client.document = dump_toml(
        replace(config, active_profile="second", revision=config.revision + 1)
    )
    sync_run(widget.presenter.refresh)
    qapp.processEvents()
    assert page.active_label.text() == "Active: Same (second)"
    assert page.profiles_box.currentData() == "second"
    config = parse_toml(client.document)
    remaining = tuple((i, p) for i, p in config.profiles if i != "second")
    client.document = dump_toml(
        replace(
            config,
            revision=config.revision + 1,
            active_profile=remaining[0][0],
            default_profile=remaining[0][0],
            profiles=remaining,
        )
    )
    sync_run(widget.presenter.refresh)
    qapp.processEvents()
    assert page.profiles_box.currentData() == "first"
    assert page.active_label.text() == "Active: Same (first)"
    widget.deleteLater()
    qapp.processEvents()


def test_activate_noop_for_active_and_offline(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, client, model, _presenter = _window(qapp)
    _two_profiles(client, widget, qapp)
    page = _page(widget)
    question = Mock()
    monkeypatch.setattr(QMessageBox, "question", question)
    page.activate_button.click()
    qapp.processEvents()
    assert question.call_count == 0
    assert client.applied == []
    model.mark_unreachable("offline")
    qapp.processEvents()
    assert not page.activate_button.isEnabled()
    page.profiles_box.setCurrentIndex(page.profiles_box.findData("second"))
    qapp.processEvents()
    page.activate_button.click()
    qapp.processEvents()
    assert question.call_count == 0
    widget.deleteLater()
    qapp.processEvents()


def test_plate_draft_preserved_across_selection_with_concise_feedback(
    qapp: QApplication,
) -> None:
    widget, client, _model, _presenter = _window(qapp)
    _two_profiles(client, widget, qapp)
    page = _page(widget)
    page.profiles_box.setCurrentIndex(page.profiles_box.findData("first"))
    page.plate_box.setCurrentIndex(page.plate_box.findData(6))
    assert page.has_unsaved_changes()
    assert "first" in page.draft_label.text()
    page.profiles_box.setCurrentIndex(page.profiles_box.findData("second"))
    qapp.processEvents()
    assert page.has_unsaved_changes()
    assert "first" in page.draft_label.text()
    page.profiles_box.setCurrentIndex(page.profiles_box.findData("first"))
    assert page.plate_box.currentData() == 6
    page.discard_changes()
    assert not page.has_unsaved_changes()
    assert page.draft_label.text() == ""
    widget.deleteLater()
    qapp.processEvents()


def test_software_profiles_fit_360_without_list_reserve(qapp: QApplication) -> None:
    widget, client, _model, _presenter = _window(qapp)
    _two_profiles(client, widget, qapp)
    page = _page(widget)
    widget.resize(360, 660)
    widget.show()
    qapp.processEvents()
    assert widget.width() == 360
    assert page.profiles_box.width() > 0
    assert page.activate_button.width() > 0
    assert page.profiles_box.width() + page.activate_button.width() <= 360
    widget.deleteLater()
    qapp.processEvents()


def test_activation_wires_through_shell_guard(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    presenter, model, client = make_presenter("")
    widget = MainWindow(presenter, model, sync_run)
    widget._poll_timer.stop()  # pyright: ignore[reportPrivateUsage]
    sync_run(presenter.refresh)
    model.apply_snapshot(parse_snapshot(VERIFIED))
    qapp.processEvents()
    base = parse_toml(client.document)
    from naga_control.gui.editors import duplicate_profile

    client.document = duplicate_profile(client.document, base.active_profile, "mmo", "MMO")
    sync_run(presenter.refresh)
    model.apply_snapshot(parse_snapshot(VERIFIED))
    qapp.processEvents()
    page = widget.device.profiles
    emitted: list[str] = []
    page.activate_requested.connect(emitted.append)
    page.profiles_box.setCurrentIndex(page.profiles_box.findData("mmo"))
    page.activate_button.click()
    qapp.processEvents()
    assert emitted == ["mmo"]
    widget.deleteLater()
    qapp.processEvents()


def test_activate_tooltip_distinguishes_active_and_pending(qapp: QApplication) -> None:
    widget, client, model, _presenter = _window(qapp)
    _two_profiles(client, widget, qapp)
    model.apply_snapshot(parse_snapshot(VERIFIED))
    qapp.processEvents()
    page = _page(widget)
    assert not page.activate_button.isEnabled()
    assert page.activate_button.toolTip() == "Already active."
    page.profiles_box.setCurrentIndex(page.profiles_box.findData("second"))
    qapp.processEvents()
    assert page.activate_button.isEnabled()
    assert "Switch to the selected" in page.activate_button.toolTip()
    model.set_apply_status("applying…")
    qapp.processEvents()
    assert not page.activate_button.isEnabled()
    assert "pending" in page.activate_button.toolTip().lower()
    widget.deleteLater()
    qapp.processEvents()


def test_plate_drafts_reject_bool_and_float(qapp: QApplication) -> None:
    from naga_control.gui.profile_plate_drafts import PlateDrafts

    drafts = PlateDrafts()
    drafts.record("first", 12, True)
    assert not drafts
    drafts.record("first", 12, 6.0)
    assert not drafts
    drafts.record("first", 12, 6)
    assert drafts
    assert drafts.pending_ids() == ["first"]
    drafts.record("first", 12, 12)
    assert not drafts
