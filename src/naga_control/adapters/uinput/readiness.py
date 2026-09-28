"""Bounded wait until a created forwarding proxy is visible to udev."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib import import_module
from time import monotonic, sleep
from typing import Protocol, cast

from naga_control.ports.forwarding import ForwardingProxySpec


class VirtualInputIdentity(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def phys(self) -> str | None: ...


class UdevAttributes(Protocol):
    def get(self, attribute: str) -> object: ...


class UdevInputDevice(Protocol):
    @property
    def sys_name(self) -> str: ...

    @property
    def is_initialized(self) -> bool: ...

    @property
    def attributes(self) -> UdevAttributes: ...


class UdevContext(Protocol):
    def list_devices(self, **kwargs: str) -> Iterable[UdevInputDevice]: ...


class _ContextFactory(Protocol):
    def __call__(self) -> UdevContext: ...


@dataclass(frozen=True, slots=True)
class InitializedVirtualInput:
    name: str
    phys: str | None


class ProxyReadinessTimeoutError(TimeoutError):
    """The forwarding proxy did not become visible before the deadline."""


class BoundedProxyReadinessWaiter:
    """Poll an injected enumerator until the proxy identity appears."""

    def __init__(
        self,
        enumerate_inputs: Callable[[], Iterable[VirtualInputIdentity]],
        *,
        timeout_seconds: float = 1.0,
        poll_interval_seconds: float = 0.01,
        sleeper: Callable[[float], None] = sleep,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if timeout_seconds <= 0 or poll_interval_seconds <= 0:
            raise ValueError("timeout and poll interval must be greater than zero")
        self._enumerate_inputs = enumerate_inputs
        self._timeout_seconds = timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._sleeper = sleeper
        self._clock = clock

    def wait_ready(self, spec: ForwardingProxySpec) -> None:
        deadline = self._clock() + self._timeout_seconds
        while True:
            if any(
                device.name == spec.name and device.phys == spec.phys
                for device in self._enumerate_inputs()
            ):
                return
            if self._clock() >= deadline:
                raise ProxyReadinessTimeoutError(
                    f"forwarding proxy {spec.name!r} was not ready before the deadline"
                )
            self._sleeper(self._poll_interval_seconds)


def create_proxy_readiness_waiter(
    *, context: UdevContext | None = None
) -> BoundedProxyReadinessWaiter:
    """Create a udev-initialization waiter for deterministic forwarding proxies."""
    active_context = context or _create_context()
    return BoundedProxyReadinessWaiter(lambda: initialized_input_identities(active_context))


def initialized_input_identities(context: UdevContext) -> tuple[InitializedVirtualInput, ...]:
    """Return identity from unquoted sysfs attributes of initialized input devices.

    Udev ``NAME``/``PHYS`` database properties are stored with surrounding
    quotes on this system, so identity is read from the ``inputN`` sysfs
    attributes instead. ``eventN`` children carry no name attribute and are
    skipped naturally.
    """
    return tuple(
        InitializedVirtualInput(name, _text(device.attributes.get("phys")))
        for device in context.list_devices(subsystem="input")
        if device.is_initialized
        and device.sys_name.startswith("input")
        and (name := _text(device.attributes.get("name"))) is not None
    )


def _create_context() -> UdevContext:
    context_factory = cast(_ContextFactory, import_module("pyudev").Context)
    return context_factory()


def _text(value: object) -> str | None:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value if isinstance(value, str) else None
