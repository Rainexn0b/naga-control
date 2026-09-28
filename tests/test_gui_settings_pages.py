import os
from collections.abc import Callable, Iterator
from typing import cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui_support import FakeClient, make_presenter, sync_run
from PySide6.QtWidgets import QApplication, QWidget

from naga_control.config import dump_toml, parse_toml
from naga_control.domain.defaults import default_configuration
from naga_control.gui.lighting_page import LightingPage
from naga_control.gui.models import ServiceModel
from naga_control.gui.power_page import PowerPage
from naga_control.gui.presenter import GuiPresenter
from naga_control.gui.scroll_page import ScrollPage
from naga_control.gui.worker import Runner


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])
    yield cast(QApplication, app)


def _refreshed[PageT: QWidget](
    qapp: QApplication,
    make_page: Callable[[GuiPresenter, ServiceModel, Runner], PageT],
) -> tuple[PageT, FakeClient]:
    presenter, model, client = make_presenter(dump_toml(default_configuration()))
    page = make_page(presenter, model, sync_run)
    sync_run(presenter.refresh)
    qapp.processEvents()
    return page, client


def _scroll_page(qapp: QApplication) -> tuple[ScrollPage, FakeClient]:
    return _refreshed(qapp, ScrollPage)


def _power_page(qapp: QApplication) -> tuple[PowerPage, FakeClient]:
    return _refreshed(qapp, PowerPage)


def _lighting_page(qapp: QApplication) -> tuple[LightingPage, FakeClient]:
    return _refreshed(qapp, LightingPage)


def test_scroll_page_loads_and_applies(qapp: QApplication) -> None:
    page, client = _scroll_page(qapp)
    profile = default_configuration().profile(default_configuration().active_profile)

    assert page.mode_box.currentText() == profile.scroll.mode
    assert page.acceleration_check.isChecked() == profile.scroll.acceleration
    assert not page.apply_button.isEnabled()

    page.mode_box.setCurrentText("free_spin")
    page.smart_reel_check.setChecked(True)
    assert page.apply_button.isEnabled()

    page.apply_button.click()
    qapp.processEvents()

    configuration = parse_toml(client.applied[0][1])
    active = configuration.profile(configuration.active_profile)
    assert active.scroll.mode == "free_spin"
    assert active.scroll.smart_reel
    assert page.status_label.text() == "applied"


def test_power_page_loads_and_applies(qapp: QApplication) -> None:
    page, client = _power_page(qapp)
    profile = default_configuration().profile(default_configuration().active_profile)

    assert page.idle_spin.value() == profile.power.idle_seconds
    assert not page.apply_button.isEnabled()

    page.idle_spin.setValue(600)
    page.threshold_spin.setValue(20)
    page.apply_button.click()
    qapp.processEvents()

    configuration = parse_toml(client.applied[0][1])
    active = configuration.profile(configuration.active_profile)
    assert (active.power.idle_seconds, active.power.low_battery_threshold) == (600, 20)
    assert page.status_label.text() == "applied"


def test_lighting_page_loads_all_zones(qapp: QApplication) -> None:
    page, _client = _lighting_page(qapp)
    profile = default_configuration().profile(default_configuration().active_profile)

    assert [row.zone for row in page.rows] == ["thumb_grid", "logo", "scroll_wheel"]
    assert page.rows[1].brightness_spin.value() == profile.lighting.logo.brightness
    assert page.rows[1].kind_box.currentText() == profile.lighting.logo.effect.kind
    assert not page.apply_button.isEnabled()


def test_lighting_page_applies_a_static_color(qapp: QApplication) -> None:
    page, client = _lighting_page(qapp)

    logo = page.rows[1]
    logo.kind_box.setCurrentText("static")
    logo.color_edit.setText("255,0,0")
    page.apply_button.click()
    qapp.processEvents()

    configuration = parse_toml(client.applied[0][1])
    active = configuration.profile(configuration.active_profile)
    assert active.lighting.logo.effect == parse_effect("static", (255, 0, 0))
    assert page.status_label.text() == "applied"


def test_lighting_page_disables_payload_editors_by_kind(qapp: QApplication) -> None:
    page, _client = _lighting_page(qapp)

    wheel = page.rows[2]
    wheel.kind_box.setCurrentText("wave")
    assert not wheel.color_edit.isEnabled()
    assert wheel.direction_box.isEnabled()

    wheel.kind_box.setCurrentText("off")
    assert not wheel.color_edit.isEnabled()
    assert not wheel.speed_box.isEnabled()
    assert not wheel.direction_box.isEnabled()


def test_lighting_page_thumb_grid_has_no_wave(qapp: QApplication) -> None:
    page, _client = _lighting_page(qapp)

    assert "wave" not in [
        page.rows[0].kind_box.itemText(i) for i in range(page.rows[0].kind_box.count())
    ]
    assert "wave" in [
        page.rows[1].kind_box.itemText(i) for i in range(page.rows[1].kind_box.count())
    ]


def test_lighting_page_rejects_bad_color_before_sending(qapp: QApplication) -> None:
    page, client = _lighting_page(qapp)

    logo = page.rows[1]
    logo.kind_box.setCurrentText("static")
    logo.color_edit.setText("not-a-color")
    page.apply_button.click()
    qapp.processEvents()

    assert client.applied == []
    assert page.status_label.text().startswith("rejected:")


def parse_effect(kind: str, color: tuple[int, int, int] | None = None) -> object:
    from typing import cast

    from naga_control.domain.profiles import LightingEffect, LightingEffectKind

    return LightingEffect(kind=cast(LightingEffectKind, kind), color=color)
