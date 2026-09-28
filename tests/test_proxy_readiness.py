from dataclasses import dataclass

import pytest

from naga_control.adapters.uinput.readiness import (
    BoundedProxyReadinessWaiter,
    ProxyReadinessTimeoutError,
    initialized_input_identities,
)
from naga_control.ports.forwarding import ForwardingProxySpec


@dataclass(frozen=True)
class FakeIdentity:
    name: str
    phys: str | None


@dataclass(frozen=True)
class FakeAttributes:
    values: dict[str, object]

    def get(self, attribute: str) -> object:
        return self.values.get(attribute)


@dataclass(frozen=True)
class FakeUdevDevice:
    sys_name: str
    is_initialized: bool
    attributes: FakeAttributes


class FakeUdevContext:
    def __init__(self, devices: tuple[FakeUdevDevice, ...]) -> None:
        self.devices = devices

    def list_devices(self, **kwargs: str) -> tuple[FakeUdevDevice, ...]:
        assert kwargs == {"subsystem": "input"}
        return self.devices


def test_waiter_returns_when_the_proxy_identity_appears() -> None:
    snapshots = [
        (),
        (FakeIdentity("other", "other"),),
        (FakeIdentity("Naga Control Forwarding Proxy", "naga-control/proxy/test"),),
    ]
    sleeps: list[float] = []
    waiter = BoundedProxyReadinessWaiter(
        lambda: snapshots.pop(0),
        timeout_seconds=1,
        poll_interval_seconds=0.05,
        sleeper=sleeps.append,
        clock=lambda: 0.0,
    )

    waiter.wait_ready(_spec())

    assert sleeps == [0.05, 0.05]


def test_waiter_times_out_without_matching_identity() -> None:
    times = iter((0.0, 0.4, 1.0))
    waiter = BoundedProxyReadinessWaiter(
        lambda: (),
        timeout_seconds=1,
        poll_interval_seconds=0.1,
        sleeper=lambda _delay: None,
        clock=lambda: next(times),
    )

    with pytest.raises(ProxyReadinessTimeoutError, match="not ready"):
        waiter.wait_ready(_spec())


def test_initialized_identity_enumeration_excludes_uninitialized_and_missing_names() -> None:
    identities = initialized_input_identities(
        FakeUdevContext(
            (
                FakeUdevDevice("input30", False, FakeAttributes({"name": b"proxy"})),
                FakeUdevDevice("input31", True, FakeAttributes({"phys": b"no-name"})),
                FakeUdevDevice("event9", True, FakeAttributes({"phys": b"event-node"})),
                FakeUdevDevice(
                    "input32",
                    True,
                    FakeAttributes({"name": b"proxy", "phys": b"naga-control/proxy/test"}),
                ),
            )
        )
    )

    assert [(item.name, item.phys) for item in identities] == [("proxy", "naga-control/proxy/test")]


def _spec() -> ForwardingProxySpec:
    return ForwardingProxySpec(
        "Naga Control Forwarding Proxy",
        "naga-control/proxy/test",
        3,
        1,
        2,
        3,
        (),
        {},
    )
