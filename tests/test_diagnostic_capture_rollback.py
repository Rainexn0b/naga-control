"""DEBT-03: fake-only ownership and interruption contracts for capture startup."""

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import replace

import pytest

from naga_control.adapters.evdev.discovery import EventNode, NagaConnection
from naga_control.diagnostics.capture import (
    AbsInfoLike,
    DeviceInfoLike,
    InputEventLike,
    OpenedSource,
    close_sources,
    open_sources,
)


class FakeDevice:
    name = "Fake Naga sibling"
    phys = None
    uniq = None

    def __init__(self, fd: int, trace: list[str]) -> None:
        self.fd = fd
        self.trace = trace
        self.closed = False
        self.close_error: BaseException | None = None

    @property
    def info(self) -> DeviceInfoLike:
        raise AssertionError("startup must validate USB ancestry, not display metadata")

    def close(self) -> None:
        self.trace.append(f"close:{self.fd}")
        if self.close_error is not None:
            raise self.close_error
        self.closed = True

    def input_props(self, verbose: bool = False) -> list[int]:
        raise AssertionError("rollback must not inspect input properties")

    def capabilities(
        self, verbose: bool = False, absinfo: bool = True
    ) -> Mapping[int, Sequence[int | tuple[int, AbsInfoLike]]]:
        raise AssertionError("rollback must not inspect capabilities")

    def async_read_loop(self) -> AsyncIterator[InputEventLike]:
        raise AssertionError("opening sources must not start the read loop")


class FakeCaptureBoundary:
    def __init__(self, product_id: str = "00e8") -> None:
        self.trace: list[str] = []
        self.nodes = tuple(
            EventNode(
                event_path=f"/fake/input/sibling-{index}",
                usb_path="/fake/physical-usb/naga",
                interface_number=f"{index:02}",
                vendor_id="1532",
                product_id=product_id,
            )
            for index in range(3)
        )
        self.connection = NagaConnection(
            usb_path=self.nodes[0].usb_path,
            vendor_id="1532",
            product_id=product_id,
            transport="wired" if product_id == "00e7" else "hyperspeed",
            serial=None,
            physical_path=None,
            nodes=self.nodes,
        )
        self.devices = tuple(FakeDevice(index, self.trace) for index in range(3))
        self.failure_phase = ""
        self.failure_index = -1
        self.failure: BaseException | None = None
        self.changed_identity: EventNode | None = None

    def fail(self, phase: str, index: int) -> None:
        self.trace.append(f"{phase}:{index}")
        if phase == self.failure_phase and index == self.failure_index:
            assert self.failure is not None
            raise self.failure

    def device_factory(self, path: str, readonly: bool = False) -> FakeDevice:
        assert readonly, "capture must open every sibling read-only"
        index = next(index for index, node in enumerate(self.nodes) if node.event_path == path)
        self.fail("open", index)
        return self.devices[index]

    def device_number(self, fd: int) -> int:
        self.fail("number", fd)
        return 100 + fd

    def identity(self, number: int) -> EventNode:
        index = number - 100
        self.fail("identity", index)
        if index == 2 and self.changed_identity is not None:
            return self.changed_identity
        return self.nodes[index]

    def open(self) -> tuple[OpenedSource, ...]:
        return open_sources(
            self.connection,
            device_factory=self.device_factory,
            device_number_resolver=self.device_number,
            identity_resolver=self.identity,
        )


@pytest.mark.parametrize("product_id", ["00e7", "00e8"])
def test_success_transfers_all_validated_sources_to_caller(product_id: str) -> None:
    boundary = FakeCaptureBoundary(product_id)

    sources = boundary.open()

    assert [source.source_id for source in sources] == [
        "interface-00",
        "interface-01",
        "interface-02",
    ]
    assert tuple(source.device for source in sources) == boundary.devices
    assert tuple(source.node for source in sources) == boundary.nodes
    assert boundary.trace == [
        f"{phase}:{index}" for index in range(3) for phase in ("open", "number", "identity")
    ]
    assert not any(device.closed for device in boundary.devices)
    close_sources(sources)
    assert all(device.closed for device in boundary.devices)
    assert boundary.trace[-3:] == ["close:0", "close:1", "close:2"]


@pytest.mark.parametrize("product_id", ["00e7", "00e8"])
@pytest.mark.parametrize("interruption_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("phase", ["open", "number", "identity"])
@pytest.mark.parametrize("later_index", [1, 2])
def test_later_interruption_closes_every_owned_source_and_rethrows_original(
    product_id: str,
    interruption_type: type[BaseException],
    phase: str,
    later_index: int,
) -> None:
    boundary = FakeCaptureBoundary(product_id)
    interruption = interruption_type("interrupted sibling startup")
    boundary.failure_phase = phase
    boundary.failure_index = later_index
    boundary.failure = interruption

    with pytest.raises(interruption_type) as raised:
        boundary.open()

    assert raised.value is interruption
    owned_count = later_index if phase == "open" else later_index + 1
    assert [device.closed for device in boundary.devices] == [
        index < owned_count for index in range(3)
    ]
    closes = [entry for entry in boundary.trace if entry.startswith("close:")]
    expected = [f"close:{index}" for index in range(later_index)]
    if phase != "open":
        expected.insert(0, f"close:{later_index}")
    assert closes == expected
    assert f"open:{later_index + 1}" not in boundary.trace
    assert boundary.trace.count(f"{phase}:{later_index}") == 1


@pytest.mark.parametrize("field", ["usb_path", "interface_number", "vendor_id", "product_id"])
def test_later_identity_mismatch_closes_new_descriptor_and_prior_siblings(field: str) -> None:
    boundary = FakeCaptureBoundary()
    boundary.changed_identity = replace(boundary.nodes[2], **{field: "not-the-same-source"})

    with pytest.raises(OSError, match="input identity changed before open"):
        boundary.open()

    assert all(device.closed for device in boundary.devices)
    assert boundary.trace[-3:] == ["close:2", "close:0", "close:1"]


@pytest.mark.parametrize("container_type", [tuple, list])
def test_close_sources_attempts_later_siblings_after_close_failure(
    container_type: type[tuple[OpenedSource, ...]] | type[list[OpenedSource]],
) -> None:
    boundary = FakeCaptureBoundary()
    sources = boundary.open()
    close_error = OSError("first sibling close failed")
    boundary.devices[0].close_error = close_error

    with pytest.raises(OSError) as raised:
        close_sources(container_type(sources))

    # A failed close cannot guarantee that fd closed, but must not strand other fds.
    actual_closes = [entry for entry in boundary.trace if entry.startswith("close:")]
    assert actual_closes == ["close:0", "close:1", "close:2"]
    assert boundary.devices[1].closed and boundary.devices[2].closed
    assert raised.value is close_error


@pytest.mark.parametrize("interruption_type", [OSError, KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize(
    ("phase", "close_failure_index"),
    [("open", 0), ("open", 1), ("identity", 0), ("identity", 1), ("identity", 2)],
)
def test_rollback_close_failure_preserves_interruption_and_attempts_every_owned_source(
    interruption_type: type[BaseException], phase: str, close_failure_index: int
) -> None:
    boundary = FakeCaptureBoundary()
    interruption = interruption_type("original startup interruption")
    boundary.failure_phase = phase
    boundary.failure_index = 2
    boundary.failure = interruption
    boundary.devices[close_failure_index].close_error = OSError("rollback close failed")

    # Capture either exception to assert primary identity and independent cleanup together.
    with pytest.raises(BaseException) as raised:
        boundary.open()

    owned_indices = list(range(2 if phase == "open" else 3))
    expected_closes = ["close:0", "close:1"]
    if phase != "open":
        expected_closes.insert(0, "close:2")
    actual_closes = [entry for entry in boundary.trace if entry.startswith("close:")]
    safely_closed = [index for index in owned_indices if index != close_failure_index]
    assert (
        raised.value is interruption,
        actual_closes,
        [boundary.devices[index].closed for index in safely_closed],
    ) == (True, expected_closes, [True] * len(safely_closed))


@pytest.mark.parametrize("first_error_type", [OSError, RuntimeError])
def test_close_sources_raises_first_ordinary_error_after_attempting_all_closes(
    first_error_type: type[Exception],
) -> None:
    boundary = FakeCaptureBoundary()
    sources = boundary.open()
    first_error = first_error_type("first close failed")
    boundary.devices[0].close_error = first_error
    boundary.devices[1].close_error = ValueError("second close failed")

    with pytest.raises(first_error_type) as raised:
        close_sources(sources)

    assert raised.value is first_error
    assert boundary.trace[-3:] == ["close:0", "close:1", "close:2"]
    assert boundary.devices[2].closed


@pytest.mark.parametrize("interruption_type", [KeyboardInterrupt, SystemExit])
def test_standalone_close_does_not_suppress_secondary_interruption(
    interruption_type: type[BaseException],
) -> None:
    boundary = FakeCaptureBoundary()
    sources = boundary.open()
    boundary.devices[0].close_error = OSError("ordinary close failed")
    interruption = interruption_type("cleanup interrupted")
    boundary.devices[1].close_error = interruption

    with pytest.raises(interruption_type) as raised:
        close_sources(sources)

    assert raised.value is interruption


@pytest.mark.parametrize("failure_type", [OSError, KeyboardInterrupt, SystemExit])
def test_rollback_preserves_primary_failure_when_all_closes_raise_ordinary_errors(
    failure_type: type[BaseException],
) -> None:
    boundary = FakeCaptureBoundary()
    primary = failure_type("validation failed")
    boundary.failure_phase = "identity"
    boundary.failure_index = 2
    boundary.failure = primary
    for device in boundary.devices:
        device.close_error = RuntimeError(f"close {device.fd} failed")

    with pytest.raises(failure_type) as raised:
        boundary.open()

    assert raised.value is primary
    assert boundary.trace[-3:] == ["close:2", "close:0", "close:1"]


@pytest.mark.parametrize("interruption_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("close_failure_index", [0, 2])
def test_rollback_does_not_suppress_secondary_close_interruption(
    interruption_type: type[BaseException], close_failure_index: int
) -> None:
    boundary = FakeCaptureBoundary()
    boundary.failure_phase = "identity"
    boundary.failure_index = 2
    boundary.failure = OSError("primary validation error")
    secondary = interruption_type("cleanup interrupted")
    boundary.devices[close_failure_index].close_error = secondary

    with pytest.raises(interruption_type) as raised:
        boundary.open()

    assert raised.value is secondary
    if close_failure_index == 2:
        assert boundary.devices[0].closed and boundary.devices[1].closed
