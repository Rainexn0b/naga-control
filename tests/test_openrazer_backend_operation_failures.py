"""Counter-driven read/write faults prove mutation boundaries and client recovery."""

from typing import Literal

import pytest
from test_openrazer_backend import FakeDevice, FakeManager
from test_openrazer_backend_failures import SnapshotFactory, assert_cleared, topology

from naga_control.adapters.openrazer.backend import OpenRazerBackend
from naga_control.domain.hardware import HardwareIssueCode, HardwareState

type Action = Literal["dpi", "set_scroll", "next_scroll"]


class FaultDevice(FakeDevice):
    def __init__(self, *, product_id: int = 0x00E8, noop: Action | None = None) -> None:
        super().__init__(product_id=product_id)
        if noop == "dpi":
            self._dpi_stages = (3, ((400, 500), (800, 900), (1200, 1300)))
        elif noop == "set_scroll":
            self._scroll_mode = 1
        self.calls: list[str] = []
        self.reads: dict[str, int] = {}
        self.faults: dict[str, tuple[int, object]] = {}
        self.fail_write = False

    def __getattribute__(self, name: str) -> object:
        if name in {"dpi", "dpi_stages", "scroll_mode", "scroll_mode_options"}:
            calls = object.__getattribute__(self, "calls")
            reads = object.__getattribute__(self, "reads")
            faults = object.__getattribute__(self, "faults")
            calls.append(f"read:{name}")
            reads[name] = reads.get(name, 0) + 1
            fault = faults.get(name)
            if fault is not None and reads[name] == fault[0]:
                if isinstance(fault[1], Exception):
                    raise fault[1]
                return fault[1]
        return super().__getattribute__(name)

    @property
    def dpi_stages(self) -> object:
        return self._dpi_stages

    @dpi_stages.setter
    def dpi_stages(self, value: object) -> None:
        self.calls.append("write:dpi_stages")
        self.stage_writes.append(value)
        self._dpi_stages = value
        if self.fail_write:
            raise RuntimeError("fake reply lost after DPI mutation")

    @property
    def scroll_mode(self) -> object:
        return self._scroll_mode

    @scroll_mode.setter
    def scroll_mode(self, value: object) -> None:
        self.calls.append("write:scroll_mode")
        self.scroll_writes.append(value)
        self._scroll_mode = value
        if self.fail_write:
            raise RuntimeError("fake reply lost after scroll mutation")


def operate(backend: OpenRazerBackend, action: Action) -> HardwareState:
    if action == "dpi":
        return backend.move_dpi_stage(1)
    if action == "set_scroll":
        return backend.set_scroll_mode("free_spin")
    return backend.move_scroll_mode(1)


@pytest.mark.parametrize("action", ["dpi", "set_scroll", "next_scroll"])
@pytest.mark.parametrize("phase", ["prewrite", "write", "refresh"])
def test_transient_action_failure_clears_state_without_retry_and_next_action_reacquires(
    action: Action, phase: str
) -> None:
    broken, awake = FaultDevice(), FaultDevice()
    wrong_transport = FaultDevice(product_id=0x00E7)
    factory = SnapshotFactory(FakeManager((broken,)), FakeManager((wrong_transport, awake)))
    backend = OpenRazerBackend(factory)
    initial = backend.rescan((topology("hyperspeed"),))
    assert initial.status == "available" and initial.generation == 1
    broken.calls.clear()
    broken.reads.clear()
    if phase == "prewrite":
        field = "dpi_stages" if action == "dpi" else "scroll_mode"
        # Cycling reads twice; inject here inside the mutation's guarded read.
        broken.faults[field] = (2 if action == "next_scroll" else 1, RuntimeError("asleep"))
    elif phase == "write":
        broken.fail_write = True
    else:
        broken.faults["dpi"] = (1, RuntimeError("fake readback timeout"))

    failed = operate(backend, action)

    assert failed is backend.state
    assert_cleared(failed, "unavailable", "device_unavailable", 1, "hyperspeed")
    assert factory.calls == 1
    prefix = [] if action != "next_scroll" else ["read:scroll_mode", "read:scroll_mode_options"]
    expected = prefix + (["read:dpi_stages"] if action == "dpi" else ["read:scroll_mode"])
    if phase != "prewrite":
        if action != "dpi":
            expected.append("read:scroll_mode_options")
        expected.append("write:dpi_stages" if action == "dpi" else "write:scroll_mode")
    if phase == "refresh":
        expected.append("read:dpi")
    assert broken.calls == expected
    assert broken.stage_writes == (
        [(3, ((400, 500), (800, 900), (1200, 1300)))]
        if action == "dpi" and phase != "prewrite"
        else []
    )
    assert broken.scroll_writes == ([1] if action != "dpi" and phase != "prewrite" else [])
    stale_calls = broken.calls.copy()

    recovered = operate(backend, action)

    assert recovered is backend.state and recovered.status == "available"
    assert recovered.generation == 2 and recovered.transport == "hyperspeed"
    assert recovered.error is None and factory.calls == 2
    assert broken.calls == stale_calls
    assert wrong_transport.calls == []
    assert wrong_transport.stage_writes == wrong_transport.scroll_writes == []
    assert awake.stage_writes == (
        [(3, ((400, 500), (800, 900), (1200, 1300)))] if action == "dpi" else []
    )
    assert awake.scroll_writes == ([1] if action != "dpi" else [])
    assert recovered.active_dpi_stage == (3 if action == "dpi" else 2)
    assert recovered.scroll_mode == ("tactile" if action == "dpi" else "free_spin")


@pytest.mark.parametrize(
    ("action", "phase", "field", "fault_read"),
    [
        ("dpi", "prewrite", "dpi_stages", 1),
        ("set_scroll", "prewrite", "scroll_mode", 1),
        ("next_scroll", "prewrite", "scroll_mode", 1),
        ("set_scroll", "prewrite", "scroll_mode_options", 1),
        ("next_scroll", "prewrite", "scroll_mode_options", 1),
        ("next_scroll", "prewrite", "scroll_mode_options", 2),
        ("dpi", "refresh", "dpi", 1),
        ("set_scroll", "refresh", "dpi", 1),
        ("next_scroll", "refresh", "dpi", 1),
    ],
)
@pytest.mark.parametrize("code", ["unsupported_capability", "invalid_response"])
def test_missing_or_malformed_action_reply_clears_state_and_blocks_further_mutations(
    action: Action, phase: str, field: str, fault_read: int, code: HardwareIssueCode
) -> None:
    device = FaultDevice()
    factory = SnapshotFactory(FakeManager((device,)))
    backend = OpenRazerBackend(factory)
    assert backend.rescan((topology("hyperspeed"),)).status == "available"
    device.calls.clear()
    device.reads.clear()
    device.faults[field] = (
        fault_read,
        AttributeError(field) if code == "unsupported_capability" else None,
    )

    state = operate(backend, action)

    assert state is backend.state
    assert_cleared(state, "unsupported", code, 1, "hyperspeed")
    assert device.stage_writes == (
        [(3, ((400, 500), (800, 900), (1200, 1300)))]
        if phase == "refresh" and action == "dpi"
        else []
    )
    assert device.scroll_writes == ([1] if phase == "refresh" and action != "dpi" else [])
    if phase == "prewrite":
        assert device.calls == (
            ["read:scroll_mode", "read:scroll_mode_options"] * fault_read
            if field == "scroll_mode_options"
            else [f"read:{field}"]
        )
    else:
        assert device.calls[-2:] == [
            "write:dpi_stages" if action == "dpi" else "write:scroll_mode",
            "read:dpi",
        ]
    calls = device.calls.copy()
    assert operate(backend, action) is state
    assert backend.move_dpi_stage(1) is state
    assert backend.refresh_state() is state
    assert factory.calls == 1 and device.calls == calls


@pytest.mark.parametrize("action", ["dpi", "set_scroll"])
def test_noop_actions_still_refresh_and_do_not_write_when_readback_fails(action: Action) -> None:
    device = FaultDevice(noop=action)
    factory = SnapshotFactory(FakeManager((device,)))
    backend = OpenRazerBackend(factory)
    assert backend.rescan((topology("hyperspeed"),)).status == "available"
    device.calls.clear()
    device.reads.clear()
    device.faults["dpi"] = (1, RuntimeError("fake readback failure"))

    state = operate(backend, action)

    assert state is backend.state
    assert_cleared(state, "unavailable", "device_unavailable", 1, "hyperspeed")
    assert device.calls == (
        ["read:dpi_stages", "read:dpi"]
        if action == "dpi"
        else ["read:scroll_mode", "read:scroll_mode_options", "read:dpi"]
    )
    assert factory.calls == 1 and device.stage_writes == device.scroll_writes == []


@pytest.mark.parametrize("field", ["scroll_mode", "scroll_mode_options"])
def test_scroll_cycle_initial_timeout_clears_state_and_next_action_reacquires(field: str) -> None:
    broken, awake = FaultDevice(), FaultDevice()
    factory = SnapshotFactory(FakeManager((broken,)), FakeManager((awake,)))
    backend = OpenRazerBackend(factory)
    initial = backend.rescan((topology("hyperspeed"),))
    assert initial.status == "available" and initial.generation == 1
    broken.calls.clear()
    broken.reads.clear()
    broken.faults[field] = (1, RuntimeError("fake initial scroll read timeout"))

    failed = backend.move_scroll_mode(1)

    assert failed is backend.state
    assert_cleared(failed, "unavailable", "device_unavailable", 1, "hyperspeed")
    expected_reads = (
        ["read:scroll_mode"]
        if field == "scroll_mode"
        else ["read:scroll_mode", "read:scroll_mode_options"]
    )
    assert broken.calls == expected_reads and factory.calls == 1
    assert broken.stage_writes == broken.scroll_writes == []
    assert awake.calls == [] and awake.stage_writes == awake.scroll_writes == []

    # A different target distinguishes this new request from retrying the failed cycle.
    recovered = backend.set_scroll_mode("precision_tactile")

    assert recovered is backend.state and recovered.status == "available"
    assert recovered.error is None and recovered.generation == 2
    assert recovered.transport == "hyperspeed" and recovered.scroll_mode == "precision_tactile"
    assert recovered.active_dpi_stage == 2 and factory.calls == 2
    assert broken.calls == expected_reads
    assert broken.stage_writes == broken.scroll_writes == []
    assert awake.stage_writes == [] and awake.scroll_writes == [2]
    assert awake.reads == {"dpi": 2, "dpi_stages": 2, "scroll_mode": 3, "scroll_mode_options": 3}


def test_read_only_refresh_failure_invalidates_client_and_next_refresh_reacquires() -> None:
    broken, awake = FaultDevice(), FaultDevice()
    factory = SnapshotFactory(FakeManager((broken,)), FakeManager((awake,)))
    backend = OpenRazerBackend(factory)
    assert backend.rescan((topology("hyperspeed"),)).status == "available"
    broken.calls.clear()
    broken.reads.clear()
    broken.faults["dpi"] = (1, RuntimeError("fake device disappeared"))

    failed = backend.refresh_state()

    assert failed is backend.state
    assert_cleared(failed, "unavailable", "device_unavailable", 1, "hyperspeed")
    assert broken.calls == ["read:dpi"] and factory.calls == 1
    recovered = backend.refresh_state()
    assert recovered is backend.state and recovered.status == "available"
    assert recovered.generation == 2 and recovered.transport == "hyperspeed"
    assert recovered.active_dpi_stage == 2 and recovered.scroll_mode == "tactile"
    assert factory.calls == 2 and broken.calls == ["read:dpi"]
    assert (
        awake.calls
        == [
            "read:dpi",
            "read:dpi_stages",
            "read:scroll_mode",
            "read:scroll_mode_options",
        ]
        * 2
    )
    assert broken.stage_writes == broken.scroll_writes == []
    assert awake.stage_writes == awake.scroll_writes == []
