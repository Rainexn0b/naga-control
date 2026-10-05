"""Lighting color wheel integration with the atomic Settings draft."""

import os
from collections.abc import Iterator
from dataclasses import replace
from typing import cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui_support import FakeClient, make_presenter, sync_run
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from naga_control.config import dump_toml, parse_toml
from naga_control.domain.defaults import default_configuration
from naga_control.domain.profiles import LightingEffect, LightingSettings, LightingZone
from naga_control.gui import lighting_page
from naga_control.gui.editors import set_power
from naga_control.gui.lighting_page import ZoneRow
from naga_control.gui.mouse_settings_page import MouseSettingsPage
from naga_control.ipc.client import StaleRevisionError


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    yield cast(QApplication, QApplication.instance() or QApplication([]))


@pytest.fixture
def settings(qapp: QApplication) -> Iterator[tuple[MouseSettingsPage, FakeClient]]:
    configuration = default_configuration()
    original = configuration.profile(configuration.active_profile)
    profile = replace(
        original,
        lighting=LightingSettings(
            thumb_grid=LightingZone(31, LightingEffect("static", (12, 34, 56))),
            logo=LightingZone(42, LightingEffect("breathing", (65, 43, 21))),
            scroll_wheel=LightingZone(53, LightingEffect("reactive", (90, 80, 70), speed=3)),
        ),
    )
    document = dump_toml(
        replace(configuration, revision=7, profiles=(("default", profile), ("other", original)))
    )
    presenter, model, client = make_presenter(document)
    page = MouseSettingsPage(presenter, model, sync_run)
    sync_run(presenter.refresh)
    qapp.processEvents()
    yield page, client
    page.close()
    page.deleteLater()
    qapp.processEvents()


def _swatch(row: ZoneRow) -> QColor:
    icon = row.color_button.icon()
    assert not icon.isNull()
    image = icon.pixmap(QSize(18, 18)).toImage()
    return image.pixelColor(9, 9)


def _choose(
    page: MouseSettingsPage,
    row: ZoneRow,
    monkeypatch: pytest.MonkeyPatch,
    selected: QColor,
    *,
    accepted: bool = True,
) -> list[tuple[QColor, QWidget | None]]:
    opened: list[tuple[QColor, QWidget | None]] = []

    class FakeDialog:
        def __init__(self, initial: QColor, parent: QWidget | None = None) -> None:
            opened.append((QColor(initial), parent))

        def exec(self) -> int:
            return int(QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected)

        def color(self) -> QColor:
            return selected

    monkeypatch.setattr(lighting_page, "ColorWheelDialog", FakeDialog)
    row.color_button.click()
    return opened


@pytest.mark.parametrize(
    ("index", "initial", "chosen"),
    [
        (0, (12, 34, 56), (201, 2, 3)),
        (1, (65, 43, 21), (4, 205, 6)),
        (2, (90, 80, 70), (7, 8, 209)),
    ],
    ids=["thumb-grid", "logo", "scroll-wheel"],
)
def test_each_zone_opens_its_own_color_and_only_accept_commits(
    settings: tuple[MouseSettingsPage, FakeClient],
    monkeypatch: pytest.MonkeyPatch,
    index: int,
    initial: tuple[int, int, int],
    chosen: tuple[int, int, int],
) -> None:
    page, client = settings
    rows = page.lighting.rows
    row = rows[index]
    assert [r.zone for r in rows] == ["thumb_grid", "logo", "scroll_wheel"]
    assert row.color_edit.isEnabled() and row.color_button.isEnabled()
    assert row.last_color == _swatch(row) == QColor(*initial)
    before = [(r.color_edit.text(), _swatch(r)) for r in rows]

    canceled = _choose(page, row, monkeypatch, QColor(*chosen), accepted=False)
    assert canceled == [(QColor(*initial), page.lighting)]
    assert [(r.color_edit.text(), _swatch(r)) for r in rows] == before
    assert not page.has_unsaved_changes()

    accepted = _choose(page, row, monkeypatch, QColor(*chosen))
    assert accepted == [(QColor(*initial), page.lighting)]
    assert row.color_edit.text() == ",".join(map(str, chosen))
    assert row.last_color == _swatch(row) == QColor(*chosen)
    assert all(
        (r.color_edit.text(), _swatch(r)) == before[i] for i, r in enumerate(rows) if i != index
    )
    assert page.has_unsaved_changes()
    assert client.applied == []


def test_manual_rgb_updates_only_its_swatch_and_wheel_initial_color(
    settings: tuple[MouseSettingsPage, FakeClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    page, _client = settings
    row = page.lighting.rows[1]
    other_swatches = [_swatch(page.lighting.rows[i]) for i in (0, 2)]
    row.color_edit.setText("0,128,255")
    assert row.last_color == _swatch(row) == QColor(0, 128, 255)
    assert [_swatch(page.lighting.rows[i]) for i in (0, 2)] == other_swatches
    assert _choose(page, row, monkeypatch, QColor(1, 2, 3), accepted=False) == [
        (QColor(0, 128, 255), page.lighting)
    ]
    assert row.color_edit.text() == "0,128,255"


@pytest.mark.parametrize("invalid", ["256,0,0", "-1,2,3", "1,2", "one,2,3"])
def test_invalid_manual_rgb_keeps_last_valid_swatch_and_wheel_can_repair_it(
    settings: tuple[MouseSettingsPage, FakeClient],
    monkeypatch: pytest.MonkeyPatch,
    invalid: str,
) -> None:
    page, _client = settings
    row = page.lighting.rows[0]
    row.color_edit.setText("10,20,30")
    row.color_edit.setText(invalid)
    assert row.last_color == _swatch(row) == QColor(10, 20, 30)
    assert "Invalid" in row.color_button.toolTip()
    assert page.has_unsaved_changes()
    assert _choose(page, row, monkeypatch, QColor(5, 60, 250)) == [
        (QColor(10, 20, 30), page.lighting)
    ]
    assert row.color_edit.text() == "5,60,250"
    assert row.last_color == _swatch(row) == QColor(5, 60, 250)


@pytest.mark.parametrize(
    ("index", "effect"),
    [(0, "off"), (1, "spectrum"), (1, "wave"), (2, "off")],
)
def test_noncolor_effect_disables_both_controls_without_losing_previous_color(
    settings: tuple[MouseSettingsPage, FakeClient],
    monkeypatch: pytest.MonkeyPatch,
    index: int,
    effect: str,
) -> None:
    page, _client = settings
    row = page.lighting.rows[index]
    row.kind_box.setCurrentText("static")
    row.color_edit.setText("23,45,67")
    assert row.kind_box.currentText() == "static"
    row.kind_box.setCurrentText(effect)
    assert not row.color_edit.isEnabled()
    assert not row.color_button.isEnabled()
    opened = _choose(page, row, monkeypatch, QColor(100, 200, 50))
    assert opened == []
    assert row.color_edit.text() == "23,45,67"
    assert row.last_color == _swatch(row) == QColor(23, 45, 67)
    row.kind_box.setCurrentText("static")
    assert row.color_edit.isEnabled() and row.color_button.isEnabled()
    assert row.color_edit.text() == "23,45,67"
    assert row.last_color == _swatch(row) == QColor(23, 45, 67)


def test_thumb_grid_does_not_offer_wave(settings: tuple[MouseSettingsPage, FakeClient]) -> None:
    page, _client = settings
    assert page.lighting.rows[0].kind_box.findText("wave") == -1
    assert page.lighting.rows[1].kind_box.findText("wave") >= 0
    assert page.lighting.rows[2].kind_box.findText("wave") >= 0


def test_wheel_apply_changes_only_selected_zone_in_one_settings_revision(
    settings: tuple[MouseSettingsPage, FakeClient],
    monkeypatch: pytest.MonkeyPatch,
    qapp: QApplication,
) -> None:
    page, client = settings
    before = parse_toml(client.document)
    row = page.lighting.rows[1]
    _choose(page, row, monkeypatch, QColor(101, 202, 3))
    page.apply_button.click()
    qapp.processEvents()

    assert len(client.applied) == 1
    expected_revision, document = client.applied[0]
    after = parse_toml(document)
    previous = before.profile(before.active_profile)
    updated = after.profile(before.active_profile)
    assert expected_revision == before.revision
    assert after.revision == before.revision + 1
    assert updated == replace(
        previous,
        lighting=replace(
            previous.lighting,
            logo=replace(previous.lighting.logo, effect=LightingEffect("breathing", (101, 202, 3))),
        ),
    )
    assert after.profile("other") == before.profile("other")
    assert after.default_profile == before.default_profile
    assert after.active_profile == before.active_profile
    assert not page.has_unsaved_changes()


def test_invalid_color_blocks_atomic_settings_apply_without_losing_drafts(
    settings: tuple[MouseSettingsPage, FakeClient], qapp: QApplication
) -> None:
    page, client = settings
    before = client.document
    page.dpi.rows[0].x_spin.setValue(2350)
    page.poll_rate_box.setCurrentIndex(page.poll_rate_box.findData(500))
    page.lighting.rows[2].color_edit.setText("256,20,30")
    page.apply_button.click()
    qapp.processEvents()
    assert client.applied == []
    assert client.document == page.model.configuration_document == before
    assert page.dpi.rows[0].x_spin.value() == 2350
    assert page.poll_rate_box.currentData() == 500
    assert page.lighting.rows[2].color_edit.text() == "256,20,30"
    assert page.has_unsaved_changes()
    assert page.status_label.text().startswith("rejected:")


def test_remote_unrelated_save_retains_wheel_draft_and_applies_over_latest(
    settings: tuple[MouseSettingsPage, FakeClient],
    monkeypatch: pytest.MonkeyPatch,
    qapp: QApplication,
) -> None:
    page, client = settings
    row = page.lighting.rows[0]
    _choose(page, row, monkeypatch, QColor(100, 110, 120))
    client.document = set_power(client.document, page.profile_id, 600, 20)
    latest = parse_toml(client.document)
    sync_run(page.presenter.refresh)
    qapp.processEvents()
    assert row.color_edit.text() == "100,110,120"
    assert row.last_color == _swatch(row) == QColor(100, 110, 120)
    assert page.has_unsaved_changes()
    page.apply_button.click()
    qapp.processEvents()
    assert len(client.applied) == 1
    assert client.applied[0][0] == latest.revision
    after = parse_toml(client.document)
    previous = latest.profile(latest.active_profile)
    assert after.revision == latest.revision + 1
    assert after.profile(latest.active_profile) == replace(
        previous,
        lighting=replace(
            previous.lighting,
            thumb_grid=replace(
                previous.lighting.thumb_grid, effect=LightingEffect("static", (100, 110, 120))
            ),
        ),
    )


@pytest.mark.parametrize("stale", [False, True], ids=["remote-save", "stale-apply"])
def test_remote_change_or_stale_apply_keeps_draft_until_discard_restores_icon(
    settings: tuple[MouseSettingsPage, FakeClient],
    monkeypatch: pytest.MonkeyPatch,
    qapp: QApplication,
    stale: bool,
) -> None:
    page, client = settings
    row = page.lighting.rows[2]
    original = parse_toml(client.document)
    _choose(page, row, monkeypatch, QColor(9, 8, 7))
    client.document = set_power(client.document, page.profile_id, 600, 20)
    authoritative = client.document
    if stale:

        async def reject(expected_revision: int, document: str) -> int:
            client.applied.append((expected_revision, document))
            raise StaleRevisionError("configuration changed elsewhere")

        monkeypatch.setattr(client, "apply_configuration", reject)
        page.apply_button.click()
        qapp.processEvents()
        assert len(client.applied) == 1
        assert client.applied[0][0] == original.revision
    else:
        sync_run(page.presenter.refresh)
        qapp.processEvents()
        assert client.applied == []
    assert page.model.configuration_document == authoritative
    assert page.has_unsaved_changes()
    assert row.color_edit.text() == "9,8,7"
    assert row.last_color == _swatch(row) == QColor(9, 8, 7)

    page.discard_button.click()
    qapp.processEvents()
    assert client.document == authoritative
    assert row.color_edit.text() == "90,80,70"
    assert row.last_color == _swatch(row) == QColor(90, 80, 70)
    assert not page.has_unsaved_changes()
    assert not page.apply_button.isEnabled()
