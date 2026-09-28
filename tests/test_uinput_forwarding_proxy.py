from collections.abc import Mapping

import pytest

from naga_control.adapters.uinput import proxy
from naga_control.ports.forwarding import ForwardingProxySpec


class FakeUInput:
    def __init__(self) -> None:
        self.events: list[tuple[int, int, int] | str] = []
        self.closed = False

    def write(self, event_type: int, code: int, value: int) -> None:
        self.events.append((event_type, code, value))

    def syn(self) -> None:
        self.events.append("syn")

    def close(self) -> None:
        self.closed = True


def test_factory_creates_proxy_with_exact_source_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[dict[str, object]] = []
    device = FakeUInput()

    class Factory:
        def __call__(self, **kwargs: object) -> FakeUInput:
            created.append(kwargs)
            return device

    modules: Mapping[str, object] = {"evdev": type("Evdev", (), {"UInput": Factory()})()}
    monkeypatch.setattr(proxy, "import_module", modules.__getitem__)
    spec = ForwardingProxySpec("proxy", "naga-control/proxy/test", 3, 1, 2, 3, (0,), {1: (30,)})

    output = proxy.UInputForwardingProxyFactory().create(spec)
    output.write(1, 30, 1)
    output.flush()
    output.close()

    assert created == [
        {
            "events": {1: (30,)},
            "name": "proxy",
            "phys": "naga-control/proxy/test",
            "bustype": 3,
            "vendor": 1,
            "product": 2,
            "version": 3,
            "input_props": [0],
        }
    ]
    assert device.events == [(1, 30, 1), "syn"]
    assert device.closed


class FakeFactory:
    def __init__(self, created: FakeUInput) -> None:
        self.created = created

    def create(self, spec: ForwardingProxySpec) -> proxy.UInputForwardingProxy:
        assert spec.name == "proxy"
        return proxy.UInputForwardingProxy(self.created)


class FakeWaiter:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.called = False

    def wait_ready(self, spec: ForwardingProxySpec) -> None:
        self.called = True
        if self.fail:
            raise TimeoutError("not ready")


def test_prepare_ready_proxy_closes_the_device_when_readiness_times_out() -> None:
    device = FakeUInput()

    with pytest.raises(TimeoutError, match="not ready"):
        proxy.prepare_ready_proxy(FakeFactory(device), FakeWaiter(fail=True), _spec())

    assert device.closed


def test_prepare_ready_proxy_returns_the_created_device_after_readiness() -> None:
    device = FakeUInput()
    waiter = FakeWaiter()

    output = proxy.prepare_ready_proxy(FakeFactory(device), waiter, _spec())

    assert waiter.called
    assert not device.closed
    output.close()
    assert device.closed


def _spec() -> ForwardingProxySpec:
    return ForwardingProxySpec("proxy", "naga-control/proxy/test", 3, 1, 2, 3, (0,), {1: (30,)})
