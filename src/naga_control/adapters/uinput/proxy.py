"""Explicit uinput forwarding-proxy construction from a prepared source spec."""

from importlib import import_module
from typing import Protocol, cast

from naga_control.ports.forwarding import (
    ForwardingProxy,
    ForwardingProxyFactory,
    ForwardingProxySpec,
    ProxyReadinessWaiter,
)


class UInputLike(Protocol):
    def write(self, event_type: int, code: int, value: int) -> None: ...
    def syn(self) -> None: ...
    def close(self) -> None: ...


class _UInputFactory(Protocol):
    def __call__(self, **kwargs: object) -> UInputLike: ...


class UInputForwardingProxy(ForwardingProxy):
    def __init__(self, device: UInputLike) -> None:
        self._device = device

    def write(self, event_type: int, code: int, value: int) -> None:
        self._device.write(event_type, code, value)

    def flush(self) -> None:
        self._device.syn()

    def close(self) -> None:
        self._device.close()


class UInputForwardingProxyFactory:
    """Create a proxy only from a source snapshot; never infer identity from a path."""

    def create(self, spec: ForwardingProxySpec) -> UInputForwardingProxy:
        evdev = import_module("evdev")
        factory = cast(_UInputFactory, evdev.UInput)
        device = factory(
            events=dict(spec.capabilities),
            name=spec.name,
            phys=spec.phys,
            bustype=spec.bustype,
            vendor=spec.vendor,
            product=spec.product,
            version=spec.version,
            input_props=list(spec.input_props),
        )
        return UInputForwardingProxy(device)


def prepare_ready_proxy(
    factory: ForwardingProxyFactory,
    waiter: ProxyReadinessWaiter,
    spec: ForwardingProxySpec,
) -> ForwardingProxy:
    """Create a proxy and wait until it is observable before returning it."""
    created = factory.create(spec)
    try:
        waiter.wait_ready(spec)
    except Exception:
        created.close()
        raise
    return created
