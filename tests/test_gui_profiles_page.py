import os
from collections.abc import Iterator
from dataclasses import replace
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui_support import FakeClient, make_presenter, sync_run
from PySide6.QtWidgets import QApplication

from naga_control.config import dump_toml, parse_toml
from naga_control.domain.defaults import default_configuration
from naga_control.gui.editors import duplicate_profile, remove_profile, set_plate_layout
from naga_control.gui.profiles_page import ProfilesPage
from naga_control.ipc.client import InvalidConfigurationError, StaleRevisionError


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])
    yield cast(QApplication, app)


def _page(qapp: QApplication, document: str = "") -> tuple[ProfilesPage, FakeClient]:
    presenter, model, client = make_presenter(document)
    page = ProfilesPage(presenter, model, sync_run)
    sync_run(presenter.refresh)
    qapp.processEvents()
    return page, client


def _apply(page: ProfilesPage, qapp: QApplication, updated: str) -> None:
    page.apply_document(updated)
    qapp.processEvents()


def test_list_shows_profiles_with_active_marker(qapp: QApplication) -> None:
    page, _client = _page(qapp)
    configuration = default_configuration()

    assert page.list_widget.count() == len(configuration.profiles)
    active_label = page.list_widget.item(0).text()
    assert active_label.startswith("▸ ")
    assert configuration.active_profile in active_label


def test_duplicate_adds_the_new_profile(qapp: QApplication) -> None:
    from naga_control.gui.editors import duplicate_profile

    page, client = _page(qapp)
    base = default_configuration()

    _apply(page, qapp, duplicate_profile(dump_toml(base), base.active_profile, "mmo", "MMO"))

    configuration = parse_toml(client.document)
    assert "mmo" in {identifier for identifier, _ in configuration.profiles}
    assert page.list_widget.count() == 2
    assert page.status_label.text() == "applied"


def test_rename_and_remove_round_trip(qapp: QApplication) -> None:
    from naga_control.gui.editors import duplicate_profile, remove_profile, rename_profile

    page, client = _page(qapp)
    base = default_configuration()
    profile_id = base.active_profile

    with_copy = duplicate_profile(dump_toml(base), profile_id, "mmo", "MMO")
    _apply(page, qapp, with_copy)
    renamed = rename_profile(client.document, profile_id, "Renamed")
    _apply(page, qapp, renamed)
    configuration = parse_toml(client.document)
    assert configuration.profile(profile_id).display_name == "Renamed"

    _apply(page, qapp, remove_profile(client.document, "mmo"))
    configuration = parse_toml(client.document)
    assert [identifier for identifier, _ in configuration.profiles] == [profile_id]
    assert not page.delete_button.isEnabled()


def test_delete_guard_reflects_profile_count(qapp: QApplication) -> None:
    page, _client = _page(qapp)
    configuration = default_configuration()

    if len(configuration.profiles) == 1:
        assert not page.delete_button.isEnabled()


def test_plate_defaults_to_active_profile_not_first(qapp: QApplication) -> None:
    base = default_configuration()
    document = duplicate_profile(dump_toml(base), base.active_profile, "mmo", "MMO")
    configuration = replace(parse_toml(document), active_profile="mmo")
    document = set_plate_layout(dump_toml(configuration), "mmo", 6)
    page, client = _page(qapp, document)

    assert page.list_widget.currentRow() == 1
    assert page.plate_box.currentText() == "6-button"
    assert page.apply_plate_button.isEnabled()
    assert "not detected automatically" in page.plate_box.toolTip()
    assert not client.applied


@pytest.mark.parametrize("layout", [12, 6, 2])
def test_apply_plate_to_inactive_profile_preserves_other_settings(
    qapp: QApplication, layout: int
) -> None:
    base = default_configuration()
    document = duplicate_profile(dump_toml(base), base.active_profile, "mmo", "MMO")
    page, client = _page(qapp, document)
    before = parse_toml(client.document)
    page.list_widget.setCurrentRow(1)
    page.plate_box.setCurrentIndex(page.plate_box.findData(layout))

    assert not client.applied
    assert client.document == document
    page.apply_plate_button.click()
    qapp.processEvents()

    after = parse_toml(client.document)
    assert client.applied == [(before.revision, client.document)]
    assert after.revision == before.revision + 1
    assert after.active_profile == before.active_profile
    assert after.default_profile == before.default_profile
    assert after.profile(before.active_profile) == before.profile(before.active_profile)
    assert after.profile("mmo") == replace(before.profile("mmo"), plate_layout=layout)
    assert after.profile("mmo").bindings == before.profile("mmo").bindings
    assert page.list_widget.currentRow() == 1
    assert page.plate_box.currentData() == layout
    assert page.status_label.text() == "applied"


def test_selection_loads_plate_and_discards_unapplied_choice(qapp: QApplication) -> None:
    base = default_configuration()
    document = duplicate_profile(dump_toml(base), base.active_profile, "mmo", "MMO")
    document = set_plate_layout(document, "mmo", 2)
    page, client = _page(qapp, document)

    assert page.plate_box.currentData() == base.profile(base.active_profile).plate_layout
    page.list_widget.setCurrentRow(1)
    assert page.plate_box.currentData() == 2
    page.plate_box.setCurrentIndex(page.plate_box.findData(6))
    page.model.set_apply_status("another status update")
    qapp.processEvents()
    assert page.plate_box.currentData() == 6
    page.list_widget.setCurrentRow(0)
    page.list_widget.setCurrentRow(1)
    assert page.plate_box.currentData() == 2

    page.list_widget.setCurrentRow(-1)
    assert page.plate_box.currentIndex() == -1
    assert not page.plate_box.isEnabled()
    assert not page.apply_plate_button.isEnabled()
    page.apply_plate_button.click()
    assert not client.applied


def test_reloads_selected_plate_and_falls_back_after_removal(qapp: QApplication) -> None:
    base = default_configuration()
    document = duplicate_profile(dump_toml(base), base.active_profile, "mmo", "MMO")
    page, client = _page(qapp, document)
    page.list_widget.setCurrentRow(1)
    client.document = set_plate_layout(document, "mmo", 6)
    sync_run(page.presenter.refresh)
    qapp.processEvents()

    assert page.list_widget.currentRow() == 1
    assert page.plate_box.currentData() == 6
    client.document = remove_profile(client.document, "mmo")
    sync_run(page.presenter.refresh)
    qapp.processEvents()
    assert page.list_widget.currentRow() == 0
    assert page.plate_box.currentData() == base.profile(base.active_profile).plate_layout
    assert not client.applied


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (InvalidConfigurationError("invalid"), "rejected: invalid values"),
        (OSError("offline"), "service unreachable"),
    ],
)
def test_plate_apply_failure_preserves_configuration(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, error: Exception, status: str
) -> None:
    page, client = _page(qapp)
    before = client.document
    monkeypatch.setattr(client, "apply_configuration", AsyncMock(side_effect=error))
    page.plate_box.setCurrentIndex(page.plate_box.findData(6))
    page.apply_plate_button.click()
    qapp.processEvents()

    assert client.document == before
    assert page.status_label.text() == status
    assert page.apply_plate_button.isEnabled() == (not isinstance(error, OSError))


def test_stale_plate_apply_preserves_choice_without_resubmitting(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, client = _page(qapp)
    configuration = parse_toml(client.document)
    client.document = set_plate_layout(client.document, configuration.active_profile, 2)
    apply = AsyncMock(side_effect=StaleRevisionError("stale"))
    monkeypatch.setattr(client, "apply_configuration", apply)
    page.plate_box.setCurrentIndex(page.plate_box.findData(6))
    page.apply_plate_button.click()
    qapp.processEvents()

    assert apply.await_count == 1
    assert apply.call_args is not None
    assert apply.call_args.args[0] == configuration.revision
    assert page.plate_box.currentData() == 6
    assert page.status_label.text() == "changed on the service; reloaded, apply again"
    page.discard_changes()
    assert page.plate_box.currentData() == 2


def test_plate_disabled_without_configuration_and_when_unreadable(qapp: QApplication) -> None:
    presenter, model, client = make_presenter("")
    page = ProfilesPage(presenter, model, sync_run)
    assert not page.plate_box.isEnabled()
    assert not page.apply_plate_button.isEnabled()

    sync_run(presenter.refresh)
    qapp.processEvents()
    valid_document = client.document
    revision = parse_toml(valid_document).revision
    model.apply_configuration(revision, "invalid toml")
    qapp.processEvents()
    assert not page.plate_box.isEnabled()
    assert not page.apply_plate_button.isEnabled()
    assert page.status_label.text() == "service configuration is unreadable"

    model.apply_configuration(revision, valid_document)
    qapp.processEvents()
    assert page.plate_box.currentData() == 12
    assert page.apply_plate_button.isEnabled()
    assert not client.applied


@pytest.mark.parametrize("confirmed", [False, True])
def test_active_profile_deletion_consults_shell_guard(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, confirmed: bool
) -> None:
    base = default_configuration()
    document = duplicate_profile(dump_toml(base), base.active_profile, "mmo", "MMO")
    page, client = _page(qapp, document)
    guard = Mock(return_value=confirmed)
    page.confirm_profile_change = guard
    monkeypatch.setattr(page, "_confirm", Mock(return_value=True))
    page.delete_button.click()
    qapp.processEvents()

    guard.assert_called_once_with()
    after = parse_toml(client.document)
    if confirmed:
        assert after.active_profile == "mmo"
        assert len(client.applied) == 1
    else:
        assert client.document == document
        assert not client.applied


def test_inactive_profile_deletion_does_not_consult_shell_guard(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = default_configuration()
    document = duplicate_profile(dump_toml(base), base.active_profile, "mmo", "MMO")
    page, client = _page(qapp, document)
    guard = Mock(return_value=False)
    page.confirm_profile_change = guard
    monkeypatch.setattr(page, "_confirm", Mock(return_value=True))
    page.list_widget.setCurrentRow(1)
    page.delete_button.click()
    qapp.processEvents()

    guard.assert_not_called()
    assert parse_toml(client.document).active_profile == base.active_profile
    assert len(client.applied) == 1


def test_profile_actions_safe_without_selection_or_reachable_service(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = default_configuration()
    document = duplicate_profile(dump_toml(base), base.active_profile, "mmo", "MMO")
    page, client = _page(qapp, document)
    prompt, confirm = Mock(), Mock()
    monkeypatch.setattr(page, "_prompt", prompt)
    monkeypatch.setattr(page, "_confirm", confirm)
    page.list_widget.setCurrentRow(-1)
    assert not page.new_button.isEnabled()
    assert not page.rename_button.isEnabled()
    assert not page.delete_button.isEnabled()
    page.new_button.click()
    page.rename_button.click()
    page.delete_button.click()
    assert not client.applied

    page.list_widget.setCurrentRow(0)
    page.model.mark_unreachable("offline")
    qapp.processEvents()
    assert not page.new_button.isEnabled()
    assert not page.rename_button.isEnabled()
    assert not page.delete_button.isEnabled()
    guard = Mock(return_value=True)
    page.confirm_profile_change = guard
    page.delete_button.click()
    guard.assert_not_called()
    prompt.assert_not_called()
    confirm.assert_not_called()
    assert not client.applied
