import os
from collections.abc import Iterator
from typing import cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui_support import FakeClient, make_presenter, sync_run
from PySide6.QtWidgets import QApplication

from naga_control.config import dump_toml, parse_toml
from naga_control.domain.defaults import default_configuration
from naga_control.gui.profiles_page import ProfilesPage


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])
    yield cast(QApplication, app)


def _page(qapp: QApplication) -> tuple[ProfilesPage, FakeClient]:
    presenter, model, client = make_presenter("")
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
