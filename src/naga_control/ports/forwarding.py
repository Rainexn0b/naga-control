"""Port and immutable specification for one per-source forwarding proxy."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol


class ForwardingProxy(Protocol):
    def write(self, event_type: int, code: int, value: int) -> None: ...

    def flush(self) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ForwardingProxySpec:
    name: str
    phys: str
    bustype: int
    vendor: int
    product: int
    version: int
    input_props: tuple[int, ...]
    capabilities: Mapping[int, Sequence[object]]


class ForwardingProxyFactory(Protocol):
    def create(self, spec: ForwardingProxySpec) -> ForwardingProxy: ...


class ProxyReadinessWaiter(Protocol):
    def wait_ready(self, spec: ForwardingProxySpec) -> None: ...
