"""Shared scroll-tray doubles for offscreen tests (fake service only)."""

import asyncio
import json
import os
from collections.abc import Iterator
from dataclasses import replace
from typing import Any, cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui_support import FakeClient, opened, sync_run
from PySide6.QtWidgets import QApplication

from naga_control.config import dump_toml, parse_toml
from naga_control.domain.defaults import default_configuration
from naga_control.domain.profiles import ScrollSettings
from naga_control.gui.app import MainWindow
from naga_control.gui.models import ServiceModel
from naga_control.gui.presenter import GuiPresenter
from naga_control.ipc.client import StaleRevisionError


def _document() -> str:
    base = default_configuration()
    profile = base.profile(base.active_profile)
    second = replace(
        profile,
        display_name="Second",
        scroll=ScrollSettings("precision_tactile", True, True),
    )
    return dump_toml(
        replace(
            base,
            active_profile="first",
            default_profile="first",
            profiles=(("first", profile), ("second", second)),
        )
    )


class ScrollClient(FakeClient):
    def __init__(self) -> None:
        super().__init__(_document())
        self.snapshot: dict[str, Any] = {
            "status": "available",
            "generation": 1,
            "transport": "hyperspeed",
            "error": None,
        }

    async def snapshot_document(self) -> str:
        return json.dumps(self.snapshot)


class GatedScrollClient(ScrollClient):
    def __init__(self, failure: str | None) -> None:
        super().__init__()
        self.failure = failure
        self.started = asyncio.Event()
        self.finish = asyncio.Event()

    async def apply_configuration(self, expected_revision: int, document: str) -> int:
        self.applied.append((expected_revision, document))
        self.started.set()
        await self.finish.wait()
        if self.failure == "stale":
            current = parse_toml(self.document)
            self.document = dump_toml(replace(current, revision=current.revision + 1))
            raise StaleRevisionError("another editor saved")
        if self.failure == "offline":
            raise ConnectionError("service disconnected")
        self.document = document
        return parse_toml(document).revision


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
