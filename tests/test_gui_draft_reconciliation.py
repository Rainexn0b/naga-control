import asyncio
import os
from collections.abc import Iterator
from dataclasses import replace
from typing import Literal, cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui_support import FakeClient, make_presenter, opened, sync_run
from PySide6.QtWidgets import QApplication

from naga_control.config import dump_toml, parse_toml
from naga_control.domain.actions import DisabledAction, MouseButtonAction
from naga_control.domain.defaults import default_configuration
from naga_control.domain.profiles import Binding, DpiSettings, DpiStage, PowerSettings, Profile
from naga_control.gui.actions_view import action_for_control, action_kind, format_action_detail
from naga_control.gui.app import MainWindow
from naga_control.gui.buttons_page import ButtonRow, ButtonsPage
from naga_control.gui.models import ServiceModel
from naga_control.gui.presenter import GuiPresenter
from naga_control.gui.settings_page import ProfileSettingsPage
from naga_control.gui.worker import CoroFactory
from naga_control.ipc.client import UnknownProfileError

type Editor = Literal["settings", "power", "buttons"]


def _document() -> str:
    configuration = default_configuration()
    original = replace(
        configuration.profile(configuration.active_profile),
        dpi=DpiSettings((DpiStage(800, 900), DpiStage(1600, 1700)), 1),
        power=PowerSettings(300, 10),
    )
    original = replace(
        original,
        bindings=replace(
            original.bindings,
            common=(
                *original.bindings.common[:2],
                Binding("ring_finger", MouseButtonAction("back")),
            ),
        ),
    )
    other = replace(
        original,
        display_name="Other",
        dpi=DpiSettings((DpiStage(2400, 2500), DpiStage(4800, 4900)), 2),
        power=PowerSettings(600, 20),
        poll_rate=500,
        scroll=replace(original.scroll, mode="free_spin", smart_reel=True),
        bindings=replace(
            original.bindings,
            common=(
                Binding("dpi_up", DisabledAction()),
                Binding("ring_finger", MouseButtonAction("forward")),
            ),
        ),
    )
    return dump_toml(
        replace(
            configuration,
            revision=7,
            active_profile="original",
            default_profile="original",
            profiles=(("original", original), ("other", other)),
        )
    )


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])
    yield cast(QApplication, app)


@pytest.fixture
def window(qapp: QApplication) -> Iterator[tuple[MainWindow, FakeClient]]:
    presenter, model, client = make_presenter(_document())
    widget = MainWindow(presenter, model, sync_run)
    widget._poll_timer.stop()  # pyright: ignore[reportPrivateUsage]
    sync_run(presenter.refresh)
    widget.show()
    qapp.processEvents()
    yield widget, client
    widget.deleteLater()
    qapp.processEvents()


def _editor(window: MainWindow, editor: Editor) -> ProfileSettingsPage | ButtonsPage:
    if editor == "settings":
        return window.settings
    if editor == "power":
        return window.device.power
    return window.buttons


def _ring_row(window: MainWindow) -> ButtonRow:
    return next(row for row in window.buttons.rows if row.control_id == "ring_finger")


def _edit(window: MainWindow, editor: Editor, *, undo: bool = False) -> None:
    if editor == "settings":
        window.settings.dpi.rows[0].x_spin.setValue(800 if undo else 2300)
    elif editor == "power":
        window.device.power.idle_spin.setValue(300 if undo else 420)
    else:
        _ring_row(window).detail_edit.setCurrentText("back" if undo else "middle")


def _assert_fields(window: MainWindow, profile: Profile) -> None:
    assert [(row.x_spin.value(), row.y_spin.value()) for row in window.settings.dpi.rows] == [
        (stage.x, stage.y) for stage in profile.dpi.stages
    ]
    assert window.settings.dpi.active_box.currentIndex() + 1 == profile.dpi.active_stage
    assert window.settings.poll_rate_box.currentData() == profile.poll_rate
    assert window.settings.scroll_section.mode_box.currentText() == profile.scroll.mode
    assert window.settings.scroll_section.smart_reel_check.isChecked() == profile.scroll.smart_reel
    assert window.device.power.idle_spin.value() == profile.power.idle_seconds
    assert window.device.power.threshold_spin.value() == profile.power.low_battery_threshold
    for control in ("ring_finger", "dpi_up"):
        row = next(row for row in window.buttons.rows if row.control_id == control)
        action = action_for_control(profile.bindings, control)
        assert action is not None
        assert row.kind_box.currentText() == action_kind(action)
        assert row.detail_edit.currentText() == format_action_detail(action)


def _external_switch(window: MainWindow, client: FakeClient, qapp: QApplication) -> None:
    configuration = parse_toml(client.document)
    client.document = dump_toml(
        replace(configuration, active_profile="other", revision=configuration.revision + 1)
    )
    sync_run(window.presenter.refresh)
    qapp.processEvents()


@pytest.mark.parametrize("editor", ["settings", "power", "buttons"])
def test_undo_to_clean_loads_new_active_fields_and_retargets_next_apply(
    qapp: QApplication, window: tuple[MainWindow, FakeClient], editor: Editor
) -> None:
    widget, client = window
    before = parse_toml(client.document)
    page = _editor(widget, editor)
    _edit(widget, editor)
    assert page.has_unsaved_changes()
    _external_switch(widget, client, qapp)
    latest = parse_toml(client.document)
    assert widget.profiles_box.currentData() == "other"
    assert page.profile_id == "original"
    assert page.has_unsaved_changes()

    _edit(widget, editor, undo=True)
    qapp.processEvents()
    assert not page.has_unsaved_changes()
    assert page.profile_id == "other"
    assert not page.apply_button.isEnabled()
    assert not page.discard_button.isEnabled()
    _assert_fields(widget, latest.profile("other"))
    assert not client.applied

    _edit(widget, editor)
    assert page.has_unsaved_changes()
    page.apply_button.click()
    qapp.processEvents()
    assert len(client.applied) == 1
    expected_revision, document = client.applied[0]
    after = parse_toml(document)
    assert expected_revision == latest.revision
    assert after.revision == latest.revision + 1
    assert after.active_profile == "other"
    assert after.default_profile == before.default_profile
    assert after.profile("original") == before.profile("original")
    updated = latest.profile("other")
    if editor == "settings":
        updated = replace(
            updated,
            dpi=replace(
                updated.dpi,
                stages=(replace(updated.dpi.stages[0], x=2300), *updated.dpi.stages[1:]),
            ),
        )
    elif editor == "power":
        updated = replace(updated, power=replace(updated.power, idle_seconds=420))
    else:
        updated = replace(
            updated,
            bindings=replace(
                updated.bindings,
                common=(
                    updated.bindings.common[0],
                    Binding("ring_finger", MouseButtonAction("middle")),
                ),
            ),
        )
    assert after.profile("other") == updated
    assert not page.has_unsaved_changes()
    _assert_fields(widget, updated)


@pytest.mark.parametrize("editor", ["settings", "power", "buttons"])
def test_retained_draft_target_warning_survives_unrelated_status_notifications(
    qapp: QApplication, window: tuple[MainWindow, FakeClient], editor: Editor
) -> None:
    widget, client = window
    page = _editor(widget, editor)
    widget.tabs.setCurrentIndex({"power": 0, "buttons": 1, "settings": 2}[editor])
    _edit(widget, editor)
    _external_switch(widget, client, qapp)
    for status in ("Unrelated save applied", "Battery refreshed", None):
        widget.model.set_apply_status(status)
        qapp.processEvents()
        assert page.status_label.isVisible()
        assert "original" in page.status_label.text()
        assert "unsaved" in page.status_label.text().lower()
        assert page.profile_id == "original"
        assert page.has_unsaved_changes()
        assert widget.profiles_box.currentData() == "other"
    assert not client.applied


class GatedClient(FakeClient):
    def __init__(self, *, fail: bool) -> None:
        super().__init__(_document())
        self.fail = fail
        self.started = asyncio.Event()
        self.finish = asyncio.Event()
        self.selected: list[str] = []

    async def select_profile(self, profile_id: str) -> int:
        self.selected.append(profile_id)
        self.started.set()
        await self.finish.wait()
        if self.fail:
            raise UnknownProfileError("profile disappeared before selection")
        configuration = parse_toml(self.document)
        configuration = replace(
            configuration, active_profile=profile_id, revision=configuration.revision + 1
        )
        self.document = dump_toml(configuration)
        return configuration.revision


def _assert_frozen(window: MainWindow, *, frozen: bool) -> None:
    for page in (window.device, window.buttons, window.settings):
        assert page.isEnabled() is not frozen
    for control in (
        window.profiles_box,
        window.settings.dpi.rows[0].x_spin,
        window.device.power.idle_spin,
        window.device.profiles.plate_box,
        _ring_row(window).detail_edit,
    ):
        assert control.isEnabled() is not frozen


@pytest.mark.parametrize("fail", [False, True], ids=["successful-switch", "failed-switch"])
async def test_gated_profile_switch_freezes_synchronously_until_queued_completion(
    qapp: QApplication, fail: bool
) -> None:
    client = GatedClient(fail=fail)
    model = ServiceModel()
    presenter = GuiPresenter(model, open_client=lambda: opened(client))
    jobs: list[CoroFactory] = []
    widget = MainWindow(presenter, model, jobs.append)
    widget._poll_timer.stop()  # pyright: ignore[reportPrivateUsage]
    task: asyncio.Task[object] | None = None
    try:
        await presenter.refresh()
        widget.show()
        qapp.processEvents()
        before = parse_toml(client.document)
        _assert_fields(widget, before.profile("original"))
        widget.profiles_box.setCurrentIndex(widget.profiles_box.findData("other"))
        _assert_frozen(widget, frozen=True)
        assert len(jobs) == 1
        assert client.selected == []

        task = asyncio.create_task(jobs.pop()())
        await asyncio.wait_for(client.started.wait(), timeout=5)
        widget.model.set_apply_status("Unrelated notification while switching")
        await presenter.refresh()
        qapp.processEvents()
        _assert_frozen(widget, frozen=True)
        _assert_fields(widget, before.profile("original"))
        assert widget.settings.profile_id == "original"
        assert not task.done()
        assert client.document == dump_toml(before)

        client.finish.set()
        await asyncio.wait_for(task, timeout=5)
        # Completion must reach Qt through its queued signal, not touch widgets from asyncio.
        _assert_frozen(widget, frozen=True)
        qapp.processEvents()
        _assert_frozen(widget, frozen=False)
        active = "original" if fail else "other"
        after = parse_toml(client.document)
        assert after.active_profile == active
        assert after.revision == before.revision + (0 if fail else 1)
        assert widget.profiles_box.currentData() == active
        for page in (widget.settings, widget.device.power, widget.buttons):
            assert page.profile_id == active
            assert not page.has_unsaved_changes()
        _assert_fields(widget, before.profile(active))
        assert widget.model.apply_status == (
            "Profile switch failed" if fail else "Profile switched"
        )
        assert client.selected == ["other"]
        assert not client.applied
        assert not jobs
    finally:
        client.finish.set()
        if task is not None:
            await task
        widget.deleteLater()
        qapp.processEvents()
