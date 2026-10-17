"""USB removal teardown: ENODEV ungrab must not poison strict cleanup.

Repo `SourceForwarder` suppresses cleanup errors, unlike the installed strict
barrier. These tests use a fake strict wrapper that mirrors the installed
ordering (release, ungrab, source-close, proxy-close, cache first Exception)
so the adapter contract is verified without claiming repo forwarding is strict.
"""

import errno
from collections.abc import Mapping, Sequence

import pytest

from naga_control.adapters.evdev.discovery import EventNode
from naga_control.adapters.evdev.source import EvdevSource, open_evdev_source


class FakeInfo:
    bustype = 3
    vendor = 0x1532
    product = 0x00E8
    version = 1


class RemovalFakeDevice:
    """Fake physical descriptor with injectable ungrab/close failures."""

    fd = 42
    info = FakeInfo()

    def __init__(
        self,
        *,
        ungrab_error: BaseException | None = None,
        close_errors: tuple[Exception, ...] = (),
    ) -> None:
        self._ungrab_error = ungrab_error
        self._close_errors = list(close_errors)
        self.ungrab_calls = 0
        self.close_calls = 0
        self.grab_calls = 0
        self.closed = False

    def grab(self) -> None:
        self.grab_calls += 1
        if self.closed:
            raise OSError(errno.EBADF, "closed descriptor")

    def ungrab(self) -> None:
        self.ungrab_calls += 1
        if self._ungrab_error is not None:
            raise self._ungrab_error

    def close(self) -> None:
        self.close_calls += 1
        if self._close_errors:
            raise self._close_errors.pop(0)
        self.closed = True

    def input_props(self, verbose: bool = False) -> Sequence[int]:
        assert not verbose
        return (1,)

    def capabilities(
        self, verbose: bool = False, absinfo: bool = True
    ) -> Mapping[int, Sequence[object]]:
        assert not verbose
        assert absinfo
        return {1: (30,)}

    def active_keys(self) -> tuple[int, ...]:
        return ()

    def absinfo(self, axis: int) -> object:
        raise AssertionError("no abs axes in removal tests")


class FakeProxy:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


def _node(
    *,
    event_path: str = "/dev/input/event5",
    usb_path: str = "/sys/devices/usb-port1",
) -> EventNode:
    return EventNode(
        event_path=event_path,
        usb_path=usb_path,
        interface_number="01",
        vendor_id="1532",
        product_id="00e8",
        serial=None,
        physical_path=None,
    )


def _source(device: RemovalFakeDevice, node: EventNode | None = None) -> EvdevSource:
    actual = node if node is not None else _node()
    return EvdevSource(
        actual,
        device,  # type: ignore[arg-type]
        identity_resolver=lambda _fd: actual,
        device_number_resolver=lambda _fd: 1,
    )


def strict_teardown(source: EvdevSource, proxy: FakeProxy, release: list[str]) -> None:
    """Mirror the installed strict order: release, ungrab, closes, first error wins."""
    first: Exception | None = None

    def attempt(operation: object) -> None:
        nonlocal first
        try:
            if callable(operation):
                operation()
        except Exception as exc:
            if first is None:
                first = exc

    attempt(lambda: release.append("release"))
    attempt(source.ungrab)
    attempt(source.close)
    attempt(proxy.close)
    if first is not None:
        raise first


def test_normal_ungrab_still_works() -> None:
    device = RemovalFakeDevice()
    source = _source(device)

    source.ungrab()
    source.close()

    assert (device.ungrab_calls, device.close_calls) == (1, 1)


def test_enodev_ungrab_permits_exactly_once_close() -> None:
    device = RemovalFakeDevice(ungrab_error=OSError(errno.ENODEV, "no such device"))
    source = _source(device)

    source.ungrab()
    source.close()
    source.close()

    assert device.ungrab_calls == 1
    assert device.close_calls == 1
    assert device.closed


def test_enodev_followed_by_close_failure_surfaces() -> None:
    close_error = OSError(errno.EIO, "close failed")
    device = RemovalFakeDevice(
        ungrab_error=OSError(errno.ENODEV, "no such device"),
        close_errors=(close_error,),
    )
    source = _source(device)

    source.ungrab()
    with pytest.raises(OSError) as caught:
        source.close()

    assert caught.value is close_error
    assert device.close_calls == 1
    # A failed close never masquerades as success: the next close retries
    # and, with no further injected failure, releases the descriptor.
    source.close()
    assert device.close_calls == 2
    assert device.closed


def test_close_failure_without_ungrab_error_surfaces() -> None:
    close_error = OSError(errno.EIO, "close failed")
    device = RemovalFakeDevice(close_errors=(close_error,))
    source = _source(device)

    with pytest.raises(OSError) as caught:
        source.close()

    assert caught.value is close_error
    assert device.close_calls == 1


@pytest.mark.parametrize("failing_errno", [errno.EIO, errno.EBADF, errno.EPERM, None])
def test_non_enodev_ungrab_propagates_exact_object(failing_errno: int | None) -> None:
    if failing_errno is None:
        error: OSError = OSError("no errno attached")
        error.errno = None  # type: ignore[assignment]
    else:
        error = OSError(failing_errno, "genuine failure")
    device = RemovalFakeDevice(ungrab_error=error)
    source = _source(device)

    with pytest.raises(OSError) as caught:
        source.ungrab()

    assert caught.value is error
    assert device.ungrab_calls == 1
    assert device.close_calls == 0


@pytest.mark.parametrize("error", [RuntimeError("boom"), KeyboardInterrupt()])
def test_non_oserror_ungrab_propagates_without_closing(error: BaseException) -> None:
    device = RemovalFakeDevice(ungrab_error=error)
    source = _source(device)

    with pytest.raises(BaseException) as caught:
        source.ungrab()

    assert caught.value is error
    assert device.close_calls == 0


def test_fresh_source_on_new_port_revalidates_normally() -> None:
    new_node = _node(event_path="/dev/input/event9", usb_path="/sys/devices/usb-port2")
    device = RemovalFakeDevice()

    source = open_evdev_source(
        new_node,
        device_factory=lambda _path: device,  # type: ignore[return-value]
        identity_resolver=lambda _number: new_node,
        device_number_resolver=lambda _fd: 7,
    )

    assert source.node == new_node
    source.revalidate()
    source.grab()
    source.ungrab()
    source.close()
    assert (device.grab_calls, device.ungrab_calls, device.close_calls) == (1, 1, 1)


def test_old_source_cannot_be_reused_after_close() -> None:
    device = RemovalFakeDevice(ungrab_error=OSError(errno.ENODEV, "no such device"))
    source = _source(device)

    source.ungrab()
    source.close()
    source.close()

    assert device.close_calls == 1
    with pytest.raises(OSError, match="closed descriptor"):
        source.grab()


def test_strict_wrapper_enodev_does_not_reach_barrier() -> None:
    device = RemovalFakeDevice(ungrab_error=OSError(errno.ENODEV, "no such device"))
    source = _source(device)
    proxy = FakeProxy()
    release: list[str] = []

    strict_teardown(source, proxy, release)

    assert release == ["release"]
    assert device.close_calls == 1
    assert proxy.close_calls == 1


def test_strict_wrapper_genuine_ungrab_error_reaches_barrier() -> None:
    genuine = OSError(errno.EIO, "genuine ungrab failure")
    device = RemovalFakeDevice(ungrab_error=genuine)
    source = _source(device)
    proxy = FakeProxy()
    release: list[str] = []

    with pytest.raises(OSError) as caught:
        strict_teardown(source, proxy, release)

    assert caught.value is genuine
    # Strict cleanup still attempts later closes despite the primary failure.
    assert device.close_calls == 1
    assert proxy.close_calls == 1


def test_strict_wrapper_close_error_reaches_barrier() -> None:
    close_error = OSError(errno.EIO, "close failed")
    device = RemovalFakeDevice(
        ungrab_error=OSError(errno.ENODEV, "no such device"),
        close_errors=(close_error,),
    )
    source = _source(device)
    proxy = FakeProxy()

    with pytest.raises(OSError) as caught:
        strict_teardown(source, proxy, [])

    assert caught.value is close_error
