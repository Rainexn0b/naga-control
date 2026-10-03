import os
from collections.abc import Iterator
from dataclasses import replace
from typing import cast
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui_support import FakeClient, make_presenter, sync_run
from PySide6.QtWidgets import QApplication

from naga_control.config import dump_toml, parse_toml
from naga_control.domain.actions import DisabledAction
from naga_control.domain.defaults import default_configuration
from naga_control.domain.profiles import (
    DpiSettings,
    DpiStage,
    LightingEffect,
    LightingSettings,
    LightingZone,
    Profile,
    ScrollSettings,
)
from naga_control.gui.editors import edit_profile, set_bindings, set_power
from naga_control.gui.mouse_settings_page import MouseSettingsPage
from naga_control.ipc.client import StaleRevisionError


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])
    yield cast(QApplication, app)


@pytest.fixture
def settings(qapp: QApplication) -> Iterator[tuple[MouseSettingsPage, FakeClient]]:
    configuration = default_configuration()
    profile = configuration.profile(configuration.active_profile)
    profile = replace(profile, dpi=DpiSettings(profile.dpi.stages[:3], 1))
    document = dump_toml(
        replace(
            configuration,
            revision=7,
            profiles=((configuration.active_profile, profile), ("other", profile)),
        )
    )
    presenter, model, client = make_presenter(document)
    page = MouseSettingsPage(presenter, model, sync_run)
    sync_run(presenter.refresh)
    qapp.processEvents()
    yield page, client
    page.close()
    page.deleteLater()
    qapp.processEvents()


def _edited(profile: Profile) -> Profile:
    return replace(
        profile,
        dpi=DpiSettings((DpiStage(2350, 2450), *profile.dpi.stages[1:]), 2),
        scroll=ScrollSettings("precision_tactile", True, True),
        lighting=LightingSettings(
            thumb_grid=LightingZone(31, LightingEffect("static", (12, 34, 56))),
            logo=LightingZone(42, LightingEffect("reactive", (65, 43, 21), speed=3)),
            scroll_wheel=LightingZone(53, LightingEffect("wave", direction="right")),
        ),
        poll_rate=500,
    )


def _edit_all(page: MouseSettingsPage) -> None:
    page.dpi.rows[0].x_spin.setValue(2350)
    page.dpi.rows[0].y_spin.setValue(2450)
    page.dpi.active_box.setCurrentIndex(1)
    page.scroll_section.mode_box.setCurrentText("precision_tactile")
    page.scroll_section.acceleration_check.setChecked(True)
    page.scroll_section.smart_reel_check.setChecked(True)
    for row, brightness, kind, color in zip(
        page.lighting.rows,
        (31, 42, 53),
        ("static", "reactive", "wave"),
        ("12,34,56", "65,43,21", ""),
        strict=True,
    ):
        row.brightness_spin.setValue(brightness)
        row.kind_box.setCurrentText(kind)
        row.color_edit.setText(color)
    page.lighting.rows[1].speed_box.setCurrentText("3")
    page.lighting.rows[2].direction_box.setCurrentText("right")
    page.poll_rate_box.setCurrentIndex(page.poll_rate_box.findData(500))


def _assert_values(page: MouseSettingsPage, profile: Profile) -> None:
    assert [(row.x_spin.value(), row.y_spin.value()) for row in page.dpi.rows] == [
        (stage.x, stage.y) for stage in profile.dpi.stages
    ]
    assert page.dpi.active_box.currentIndex() + 1 == profile.dpi.active_stage
    assert page.scroll_section.mode_box.currentText() == profile.scroll.mode
    assert page.scroll_section.acceleration_check.isChecked() == profile.scroll.acceleration
    assert page.scroll_section.smart_reel_check.isChecked() == profile.scroll.smart_reel
    assert page.poll_rate_box.currentData() == profile.poll_rate
    for row in page.lighting.rows:
        zone = cast(LightingZone, getattr(profile.lighting, row.zone))
        assert row.brightness_spin.value() == zone.brightness
        assert row.kind_box.currentText() == zone.effect.kind
        if zone.effect.color is not None:
            assert row.color_edit.text() == ",".join(str(value) for value in zone.effect.color)
        if zone.effect.speed is not None:
            assert row.speed_box.currentText() == str(zone.effect.speed)
        if zone.effect.direction is not None:
            assert row.direction_box.currentText() == zone.effect.direction


def test_single_apply_commits_all_sections_in_one_revision(
    qapp: QApplication, settings: tuple[MouseSettingsPage, FakeClient]
) -> None:
    page, client = settings
    before = parse_toml(client.document)
    original = before.profile(before.active_profile)
    _assert_values(page, original)
    assert not page.has_unsaved_changes()
    assert not page.apply_button.isEnabled()
    _edit_all(page)
    assert page.has_unsaved_changes()
    assert page.apply_button.isEnabled()
    page.apply_button.click()
    qapp.processEvents()

    assert len(client.applied) == 1
    expected_revision, document = client.applied[0]
    after = parse_toml(document)
    assert expected_revision == before.revision
    assert after.revision == before.revision + 1
    assert after.profile(before.active_profile) == _edited(original)
    assert after.profile("other") == before.profile("other")
    assert after.default_profile == before.default_profile
    assert after.active_profile == before.active_profile
    assert page.model.configuration_document == document
    assert not page.has_unsaved_changes()
    assert not page.apply_button.isEnabled()
    assert not page.discard_button.isEnabled()


def test_managed_sections_have_no_subscriptions_or_visible_apply(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    presenter, model, _client = make_presenter("")
    subscribe = Mock(wraps=model.add_listener)
    monkeypatch.setattr(model, "add_listener", subscribe)
    page = MouseSettingsPage(presenter, model, sync_run)
    sync_run(presenter.refresh)
    page.resize(1200, 800)
    page.show()
    qapp.processEvents()
    try:
        assert subscribe.call_count == 1
        assert page.apply_button.isVisible()
        for section in (page.dpi, page.scroll_section, page.lighting):
            assert not section.apply_button.isVisible()
            assert not section.discard_button.isVisible()
    finally:
        page.close()
        page.deleteLater()


def test_invalid_lighting_rejects_every_section_and_retains_drafts(
    qapp: QApplication, settings: tuple[MouseSettingsPage, FakeClient]
) -> None:
    page, client = settings
    original_document = client.document
    before = parse_toml(original_document)
    expected = _edited(before.profile(before.active_profile))
    _edit_all(page)
    page.lighting.rows[1].color_edit.setText("not-a-color")
    page.apply_button.click()
    qapp.processEvents()

    assert client.applied == []
    assert client.document == original_document
    assert page.model.configuration_document == original_document
    assert page.model.configuration_revision == before.revision
    assert page.has_unsaved_changes()
    assert page.apply_button.isEnabled()
    assert page.discard_button.isEnabled()
    assert page.lighting.rows[1].color_edit.text() == "not-a-color"
    assert page.status_label.text().startswith("rejected:")
    page.lighting.rows[1].color_edit.setText("65,43,21")
    _assert_values(page, expected)


@pytest.mark.parametrize("saved_section", ["power", "bindings"])
def test_unrelated_save_keeps_draft_and_applies_over_latest_document(
    qapp: QApplication, settings: tuple[MouseSettingsPage, FakeClient], saved_section: str
) -> None:
    page, client = settings
    before = parse_toml(client.document)
    profile_id = before.active_profile
    _edit_all(page)
    if saved_section == "power":
        updated = set_power(client.document, profile_id, 600, 20)
    else:
        updated = set_bindings(client.document, profile_id, {"ring_finger": DisabledAction()})
    client.document = updated
    sync_run(page.presenter.refresh)
    qapp.processEvents()
    latest = parse_toml(updated)
    assert page.has_unsaved_changes()
    _assert_values(page, _edited(before.profile(profile_id)))
    page.apply_button.click()
    qapp.processEvents()

    assert len(client.applied) == 1
    assert client.applied[0][0] == latest.revision
    after = parse_toml(client.document)
    assert after.revision == latest.revision + 1
    assert after.profile(profile_id) == _edited(latest.profile(profile_id))
    assert after.profile("other") == latest.profile("other")
    assert not page.has_unsaved_changes()


def test_apply_does_not_rewrite_clean_settings_sections(
    qapp: QApplication, settings: tuple[MouseSettingsPage, FakeClient]
) -> None:
    page, client = settings
    profile_id = page.profile_id
    original_dpi = parse_toml(client.document).profile(profile_id).dpi
    page.dpi.rows[0].x_spin.setValue(2350)
    client.document = edit_profile(client.document, profile_id, _edited)
    sync_run(page.presenter.refresh)
    qapp.processEvents()
    latest = parse_toml(client.document)
    page.apply_button.click()
    qapp.processEvents()

    assert len(client.applied) == 1
    after = parse_toml(client.document)
    expected_dpi = replace(
        original_dpi,
        stages=(replace(original_dpi.stages[0], x=2350), *original_dpi.stages[1:]),
    )
    assert after.profile(profile_id) == replace(latest.profile(profile_id), dpi=expected_dpi)
    assert client.applied[0][0] == latest.revision
    assert after.revision == latest.revision + 1


@pytest.mark.parametrize("discard", [False, True], ids=["apply-original", "discard-to-active"])
def test_remote_profile_switch_keeps_draft_target_until_apply_or_discard(
    qapp: QApplication, settings: tuple[MouseSettingsPage, FakeClient], discard: bool
) -> None:
    page, client = settings
    before = parse_toml(client.document)
    profile_id = before.active_profile
    _edit_all(page)
    switched = replace(before, revision=before.revision + 1, active_profile="other")
    client.document = dump_toml(switched)
    sync_run(page.presenter.refresh)
    qapp.processEvents()

    assert page.profile_id == profile_id
    assert page.has_unsaved_changes()
    _assert_values(page, _edited(before.profile(profile_id)))
    if discard:
        page.discard_changes()
        assert client.applied == []
        assert page.profile_id == "other"
        _assert_values(page, switched.profile("other"))
    else:
        page.apply_button.click()
        qapp.processEvents()
        assert len(client.applied) == 1
        after = parse_toml(client.document)
        assert client.applied[0][0] == switched.revision
        assert after.revision == switched.revision + 1
        assert after.active_profile == "other"
        assert after.profile(profile_id) == _edited(before.profile(profile_id))
        assert after.profile("other") == switched.profile("other")
    assert not page.has_unsaved_changes()


def test_stale_apply_refreshes_model_but_retains_draft_until_authoritative_discard(
    qapp: QApplication,
    settings: tuple[MouseSettingsPage, FakeClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page, client = settings
    before = parse_toml(client.document)
    _edit_all(page)
    client.document = set_power(client.document, before.active_profile, 600, 20)
    authoritative = client.document

    async def stale(expected_revision: int, document: str) -> int:
        client.applied.append((expected_revision, document))
        raise StaleRevisionError("configuration changed elsewhere")

    monkeypatch.setattr(client, "apply_configuration", stale)
    page.apply_button.click()
    qapp.processEvents()

    assert len(client.applied) == 1
    assert client.applied[0][0] == before.revision
    assert client.document == authoritative
    assert page.model.configuration_document == authoritative
    assert page.model.configuration_revision == before.revision + 1
    assert page.has_unsaved_changes()
    assert page.apply_button.isEnabled()
    _assert_values(page, _edited(before.profile(before.active_profile)))
    page.discard_button.click()
    _assert_values(page, parse_toml(authoritative).profile(before.active_profile))
    assert not page.has_unsaved_changes()
    assert len(client.applied) == 1


def test_connectivity_failure_keeps_every_draft(
    qapp: QApplication,
    settings: tuple[MouseSettingsPage, FakeClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page, client = settings
    before = parse_toml(client.document)
    _edit_all(page)

    async def disconnected(expected_revision: int, document: str) -> int:
        client.applied.append((expected_revision, document))
        raise ConnectionError("service disconnected")

    monkeypatch.setattr(client, "apply_configuration", disconnected)
    page.apply_button.click()
    qapp.processEvents()

    assert len(client.applied) == 1
    assert parse_toml(client.document) == before
    assert not page.model.connection.reachable
    assert page.has_unsaved_changes()
    assert page.apply_button.isEnabled()
    assert page.discard_button.isEnabled()
    _assert_values(page, _edited(before.profile(before.active_profile)))


@pytest.mark.parametrize("add", [True, False], ids=["add-stage", "remove-stage"])
def test_stage_structure_changes_mark_settings_dirty_without_value_edits(
    qapp: QApplication, settings: tuple[MouseSettingsPage, FakeClient], add: bool
) -> None:
    page, client = settings
    before = parse_toml(client.document)
    stages = before.profile(before.active_profile).dpi.stages
    if add:
        page.dpi.add_button.click()
        expected = (*stages, stages[-1])
    else:
        page.dpi.remove_stage(len(stages) - 1)
        expected = stages[:-1]
    assert page.dpi.has_unsaved_changes()
    assert page.has_unsaved_changes()
    assert page.apply_button.isEnabled()
    page.apply_button.click()
    qapp.processEvents()
    assert len(client.applied) == 1
    after = parse_toml(client.document)
    assert after.profile(before.active_profile).dpi.stages == expected
    assert after.revision == before.revision + 1
    assert not page.has_unsaved_changes()


def test_shown_settings_columns_reflow_and_scroll_at_narrow_width(
    qapp: QApplication, settings: tuple[MouseSettingsPage, FakeClient]
) -> None:
    page, _client = settings
    page.resize(1200, 700)
    page.show()
    qapp.processEvents()
    columns = page.columns
    assert columns.isVisible()
    assert not columns.is_stacked
    assert columns.columns_layout.getItemPosition(1) == (0, 1, 1, 1)
    page.resize(640, 400)
    qapp.processEvents()
    assert columns.viewport().width() < 850
    assert columns.is_stacked
    assert columns.columns_layout.getItemPosition(1) == (1, 0, 1, 1)
    assert columns.verticalScrollBar().maximum() > 0
    assert columns.horizontalScrollBar().maximum() == 0
    assert page.apply_button.isVisible()
    page.resize(1200, 700)
    qapp.processEvents()
    assert not columns.is_stacked
    assert columns.columns_layout.getItemPosition(1) == (0, 1, 1, 1)
