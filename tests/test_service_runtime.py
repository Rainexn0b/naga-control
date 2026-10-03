import asyncio
from dataclasses import replace

import pytest

from naga_control.adapters.evdev.discovery import EventNode, NagaConnection
from naga_control.config import dump_toml
from naga_control.domain.defaults import default_configuration
from naga_control.domain.hardware import HardwareState, SettingsFailure
from naga_control.domain.profiles import Configuration, Profile
from naga_control.ports.hardware import NagaTopology
from naga_control.service.runtime import (
    NagaService,
    StaleConfigurationRevisionError,
    UnknownProfileError,
)


class Worker:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.applied: list[object] = []
        self.settings_failures: tuple[SettingsFailure, ...] = ()
        self.rescan_state: HardwareState | None = None
        self.refreshed_state: HardwareState | None = None
        self.refresh_calls = 0

    async def start(self) -> None:
        self.events.append("start")

    def mark_topology_stale(self) -> None:
        self.events.append("stale")

    async def rescan(self, connections: tuple[NagaTopology, ...]) -> HardwareState:
        self.events.append(f"rescan:{len(connections)}")
        if self.rescan_state is not None:
            return self.rescan_state
        return HardwareState("unavailable", 1)

    async def refresh_state(self) -> HardwareState:
        self.refresh_calls += 1
        if self.refreshed_state is not None:
            return self.refreshed_state
        return HardwareState("unavailable", 1)

    async def apply_profile_settings(
        self, profile: Profile
    ) -> tuple[HardwareState, tuple[SettingsFailure, ...]]:
        self.events.append("settings")
        self.applied.append(profile)
        return HardwareState("unavailable", 1), self.settings_failures

    async def stop(self) -> None:
        self.events.append("stop")


class Session:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def start(self) -> None:
        self.events.append("start")

    async def stop(self) -> None:
        self.events.append("stop")

    def release_all(self) -> None:
        self.events.append("release")


def test_service_starts_one_connection_and_releases_before_shutdown() -> None:
    asyncio.run(_exercise_service())


async def _exercise_service() -> None:
    worker = Worker()
    session = Session()
    service = NagaService(
        lambda: (_connection(),),
        lambda: None,
        worker,
        lambda connection, configuration: session,
    )

    state = await service.start()
    service.release_all()
    await service.stop()

    assert state.status == "unavailable"
    assert worker.events == ["start", "rescan:1", "settings", "stop"]
    assert session.events == ["start", "release", "stop"]


def test_topology_change_stops_the_old_session_and_builds_a_new_one() -> None:
    asyncio.run(_exercise_replug())


async def _exercise_replug() -> None:
    worker = Worker()
    sessions: list[Session] = []
    service = NagaService(
        lambda: (_connection(),),
        lambda: None,
        worker,
        lambda connection, configuration: _session(sessions),
    )
    await service.start()

    await service.apply_topology((_connection(),))

    assert len(sessions) == 2
    assert sessions[0].events == ["start", "stop"]
    assert sessions[1].events == ["start"]
    await service.stop()
    assert worker.events == ["start", "rescan:1", "settings", "rescan:1", "settings", "stop"]


async def test_hardware_rescan_does_not_rebuild_input_forwarding() -> None:
    worker = Worker()
    sessions: list[Session] = []
    service = NagaService(
        lambda: (_connection(),),
        lambda: None,
        worker,
        lambda connection, configuration: _session(sessions),
    )
    await service.start()

    service.mark_topology_stale()
    await service.rescan((_connection(),))

    assert len(sessions) == 1
    assert sessions[0].events == ["start"]
    assert worker.events == ["start", "rescan:1", "settings", "stale", "rescan:1"]
    await service.stop()


async def test_topology_application_applies_profile_settings_and_reports_failures() -> None:
    worker = Worker()
    worker.settings_failures = (SettingsFailure("scroll_mode", "boom"),)
    service = NagaService(
        lambda: (_connection(),),
        lambda: None,
        worker,
        lambda connection, configuration: Session(),
    )
    await service.start()

    assert worker.applied == [default_configuration().profile("default")]
    assert service.snapshot()["settings_failures"] == ["scroll_mode: boom"]
    await service.stop()


async def test_device_action_state_updates_the_service_snapshot() -> None:
    service = NagaService(
        lambda: (_connection(),),
        lambda: None,
        Worker(),
        lambda connection, configuration: Session(),
    )
    await service.start()

    service.record_hardware_state(HardwareState("unavailable", 2, transport="wired"))

    assert service.snapshot() == {
        "status": "unavailable",
        "generation": 2,
        "transport": "wired",
        "error": None,
        "settings_failures": [],
        "calibrating": False,
        "observed": {},
    }
    await service.stop()


def test_topology_removal_stops_the_session_without_building_one() -> None:
    asyncio.run(_exercise_unplug())


async def _exercise_unplug() -> None:
    worker = Worker()
    sessions: list[Session] = []
    service = NagaService(
        lambda: (_connection(),),
        lambda: None,
        worker,
        lambda connection, configuration: _session(sessions),
    )
    await service.start()

    state = await service.apply_topology(())

    assert state.status == "unavailable"
    assert len(sessions) == 1
    assert sessions[0].events == ["start", "stop"]
    await service.stop()


def _session(sessions: list[Session]) -> Session:
    session = Session()
    sessions.append(session)
    return session


def test_calibration_rebuilds_passthrough_then_adopts_observed_settings() -> None:
    asyncio.run(_exercise_calibration())


async def _exercise_calibration() -> None:
    from naga_control.domain.hardware import HardwareDpiStage

    worker = Worker()
    store = Store()
    configurations: list[object] = []

    def factory(connection: object, configuration: object) -> Session:
        configurations.append(configuration)
        return _session([])

    service = NagaService(
        lambda: (_connection(),),
        lambda: None,
        worker,
        factory,
        store,
    )
    await service.start()
    assert service.snapshot()["calibrating"] is False

    assert await service.begin_calibration() is True

    calibration_profile = _active_profile(configurations[-1])
    assert calibration_profile.bindings == calibration_profile.bindings.__class__(
        common=(), plate_2=(), plate_6=(), plate_12=()
    )
    assert service.snapshot()["calibrating"] is True

    worker.rescan_state = HardwareState(
        "available",
        3,
        transport="hyperspeed",
        dpi=HardwareDpiStage(800, 800),
        dpi_stages=(HardwareDpiStage(400, 400), HardwareDpiStage(800, 800)),
        active_dpi_stage=2,
        max_dpi=30000,
        scroll_mode="free_spin",
        scroll_mode_options=("tactile", "free_spin"),
        scroll_acceleration=False,
        scroll_smart_reel=True,
    )
    assert await service.end_calibration() is False

    adopted = _active_profile(service.configuration_document())
    assert [(stage.x, stage.y) for stage in adopted.dpi.stages] == [(400, 400), (800, 800)]
    assert adopted.dpi.active_stage == 2
    assert (adopted.scroll.mode, adopted.scroll.acceleration, adopted.scroll.smart_reel) == (
        "free_spin",
        False,
        True,
    )
    assert service.configuration_revision() == 1
    assert store.saved and _active_profile(store.saved[-1]) is not None
    saved = store.saved[-1]
    assert isinstance(saved, Configuration)
    assert saved.revision == 1
    assert service.snapshot()["calibrating"] is False
    await service.stop()


def _active_profile(source: object) -> Profile:
    if isinstance(source, str):
        from naga_control.config import parse_toml

        configuration = parse_toml(source)
    else:
        configuration = source
    assert isinstance(configuration, object)
    return configuration.profile(configuration.active_profile)  # type: ignore[attr-defined]


class Store:
    def __init__(self) -> None:
        self.saved: list[object] = []

    def load(self) -> None:
        return None

    def save(self, configuration: object) -> None:
        self.saved.append(configuration)


def test_apply_configuration_persists_and_rebuilds_with_the_new_profile() -> None:
    asyncio.run(_exercise_apply())


async def _exercise_apply() -> None:
    store = Store()
    configurations: list[object] = []
    service = _service(store=store, configurations=configurations)
    await service.start()
    updated = replace(default_configuration(), revision=1)

    revision = await service.apply_configuration(0, dump_toml(updated))

    assert revision == 1
    assert service.configuration_revision() == 1
    assert store.saved == [configurations[1]]
    assert configurations[1] == updated
    assert len(configurations) == 2
    await service.stop()


def test_apply_configuration_rejects_stale_revisions_without_touching_state() -> None:
    asyncio.run(_exercise_stale())


async def _exercise_stale() -> None:
    store = Store()
    service = _service(store=store)
    await service.start()
    updated = replace(default_configuration(), revision=1)

    with pytest.raises(StaleConfigurationRevisionError):
        await service.apply_configuration(7, dump_toml(updated))
    with pytest.raises(StaleConfigurationRevisionError):
        await service.apply_configuration(0, dump_toml(default_configuration()))

    assert store.saved == []
    assert service.configuration_revision() == 0
    await service.stop()


def test_select_profile_persists_a_bumped_revision_and_rebuilds() -> None:
    asyncio.run(_exercise_select())


async def _exercise_select() -> None:
    store = Store()
    configurations: list[object] = []
    service = _service(store=store, configurations=configurations)
    await service.start()

    revision = await service.select_profile("default")

    assert revision == 1
    assert service.configuration_revision() == 1
    assert len(configurations) == 2
    assert store.saved and store.saved[0] is configurations[1]
    await service.stop()


async def _exercise_unknown_profile() -> None:
    service = _service()
    await service.start()

    with pytest.raises(UnknownProfileError):
        await service.select_profile("missing")
    await service.stop()


def test_select_profile_rejects_an_unknown_profile() -> None:
    asyncio.run(_exercise_unknown_profile())


def _service(
    *,
    store: Store | None = None,
    configurations: list[object] | None = None,
) -> NagaService:
    return NagaService(
        lambda: (_connection(),),
        lambda: None,
        Worker(),
        lambda connection, configuration: _record(configuration, configurations),
        store,
    )


def _record(configuration: object, configurations: list[object] | None) -> Session:
    if configurations is not None:
        configurations.append(configuration)
    return Session()


def _connection() -> NagaConnection:
    node = EventNode("/dev/input/event5", "/sys/usb", "01", "1532", "00e8")
    return NagaConnection("/sys/usb", "1532", "00e8", "hyperspeed", None, None, (node,))
