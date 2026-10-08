"""Shared profile-tray doubles for offscreen tests (fake service only)."""

import asyncio
import json
import os
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui_support import FakeClient

from naga_control.config import dump_toml, parse_toml
from naga_control.domain.defaults import default_configuration
from naga_control.ipc.client import UnknownProfileError


def _verified_snapshot() -> str:
    return json.dumps(
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


def _document() -> str:
    base = default_configuration()
    profile = base.profile(base.active_profile)
    return dump_toml(
        replace(
            base,
            active_profile="first",
            default_profile="first",
            profiles=(
                ("first", replace(profile, display_name="Same")),
                ("second", replace(profile, display_name="Same")),
                ("third", replace(profile, display_name="Third")),
            ),
        )
    )


class SelectingClient(FakeClient):
    def __init__(self) -> None:
        super().__init__(_document())
        self.selected: list[str] = []

    async def snapshot_document(self) -> str:
        return _verified_snapshot()

    async def select_profile(self, profile_id: str) -> int:
        self.selected.append(profile_id)
        config = parse_toml(self.document)
        config = replace(config, active_profile=profile_id, revision=config.revision + 1)
        self.document = dump_toml(config)
        return config.revision


class GatedClient(SelectingClient):
    def __init__(self, *, fail: bool) -> None:
        super().__init__()
        self.fail = fail
        self.started = asyncio.Event()
        self.finish = asyncio.Event()

    async def select_profile(self, profile_id: str) -> int:
        self.selected.append(profile_id)
        self.started.set()
        await self.finish.wait()
        if self.fail:
            raise UnknownProfileError("profile disappeared")
        config = parse_toml(self.document)
        config = replace(config, active_profile=profile_id, revision=config.revision + 1)
        self.document = dump_toml(config)
        return config.revision
