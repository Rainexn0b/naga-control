"""Owned forwarding-proxy creation and readiness rollback with injected fakes."""

import asyncio

import pytest
from test_uinput_creation_failures import Factory, inject_uinput
from test_uinput_output_failures import Sink

from naga_control.adapters.uinput import proxy
from naga_control.ports.forwarding import ForwardingProxySpec


class Waiter:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.calls: list[ForwardingProxySpec] = []

    def wait_ready(self, spec: ForwardingProxySpec) -> None:
        self.calls.append(spec)
        if self.error is not None:
            raise self.error


@pytest.mark.parametrize(
    "error_type", [OSError, RuntimeError, asyncio.CancelledError, KeyboardInterrupt]
)
def test_create_failure_does_not_wait_or_close_an_unowned_proxy(
    monkeypatch: pytest.MonkeyPatch, error_type: type[BaseException]
) -> None:
    sink = Sink()
    error = error_type("create failed")
    factory = Factory(sink, error)
    inject_uinput(monkeypatch, factory)
    waiter = Waiter()
    spec = ForwardingProxySpec("fake-proxy", "fake/phys", 6, 1, 2, 3, (), {1: (30,)})

    with pytest.raises(error_type) as caught:
        proxy.prepare_ready_proxy(proxy.UInputForwardingProxyFactory(), waiter, spec)

    assert caught.value is error
    assert len(factory.calls) == 1
    assert sink.calls == []
    assert waiter.calls == []


@pytest.mark.parametrize(
    "error_type", [TimeoutError, RuntimeError, asyncio.CancelledError, KeyboardInterrupt]
)
@pytest.mark.parametrize("close_type", [None, OSError, RuntimeError])
def test_readiness_failure_closes_provisional_proxy_and_preserves_primary(
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[BaseException],
    close_type: type[Exception] | None,
) -> None:
    sink = Sink()
    if close_type is not None:
        sink.close_errors = [close_type("secondary close failed")]
    factory = Factory(sink)
    inject_uinput(monkeypatch, factory)
    error = error_type("readiness failed")
    waiter = Waiter(error)
    # Placeholder markers identify an already-owned proxy, not a physical source.
    spec = ForwardingProxySpec("fake-proxy", "fake/phys", 6, 1, 2, 3, (), {1: (30,)})

    with pytest.raises(error_type) as caught:
        proxy.prepare_ready_proxy(proxy.UInputForwardingProxyFactory(), waiter, spec)

    assert caught.value is error
    assert waiter.calls == [spec]
    assert len(factory.calls) == 1
    assert sink.calls == ["close"]
