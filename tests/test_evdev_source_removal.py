"""USB removal teardown: ENODEV ungrab recovers cleanly through strict cleanup.

Repo `SourceForwarder` caches the first ordinary cleanup failure and re-raises
the same object. `EvdevSource.ungrab` ignores only `ENODEV`, so removal plus a
successful close is clean recovery, while `EIO`/`EBADF` remain a barrier.
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

    def read(self) -> object:
        raise BlockingIOError(errno.EAGAIN, "no pending frames")

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


def _started_forwarder(device: RemovalFakeDevice, proxy: FakeProxy, release: list[str]) -> object:
    from naga_control.service.source_forwarding import SourceForwarder

    source = _source(device)
    forwarder = SourceForwarder(source, lambda: proxy, lambda: release.append("release"))  # type: ignore[arg-type]
    forwarder.start()
    release.clear()
    device.ungrab_calls = 0
    device.close_calls = 0
    proxy.close_calls = 0
    return forwarder


def test_real_forwarder_enodev_recovers_cleanly() -> None:
    device = RemovalFakeDevice(ungrab_error=OSError(errno.ENODEV, "no such device"))
    proxy = FakeProxy()
    release: list[str] = []
    forwarder = _started_forwarder(device, proxy, release)  # type: ignore[assignment]
    from naga_control.service.source_forwarding import SourceForwarder as Real

    assert isinstance(forwarder, Real)
    forwarder.stop()  # type: ignore[attr-defined]
    assert release == ["release"]
    assert device.close_calls == 1
    assert proxy.close_calls == 1
    forwarder.stop()  # type: ignore[attr-defined]
    assert release == ["release"]
    assert device.close_calls == 1


def test_real_forwarder_genuine_ungrab_is_a_barrier() -> None:
    genuine = OSError(errno.EIO, "genuine ungrab failure")
    device = RemovalFakeDevice(ungrab_error=genuine)
    proxy = FakeProxy()
    release: list[str] = []
    forwarder = _started_forwarder(device, proxy, release)  # type: ignore[assignment]
    with pytest.raises(OSError) as caught:
        forwarder.stop()  # type: ignore[attr-defined]
    assert caught.value is genuine
    assert release == ["release"]
    assert device.close_calls == 1
    assert proxy.close_calls == 1
    with pytest.raises(OSError) as cached:
        forwarder.stop()  # type: ignore[attr-defined]
    assert cached.value is genuine
    assert device.close_calls == 1


def test_real_forwarder_close_error_is_a_barrier_after_enodev() -> None:
    close_error = OSError(errno.EIO, "close failed")
    device = RemovalFakeDevice(
        ungrab_error=OSError(errno.ENODEV, "no such device"),
        close_errors=(close_error,),
    )
    proxy = FakeProxy()
    forwarder = _started_forwarder(device, proxy, [])  # type: ignore[assignment]
    with pytest.raises(OSError) as caught:
        forwarder.stop()  # type: ignore[attr-defined]
    assert caught.value is close_error


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
