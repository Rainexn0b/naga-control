"""Compose and run physically discovered sources for the first remapping slice."""

import asyncio
from collections.abc import Callable
from contextlib import suppress
from typing import Protocol

from naga_control.adapters.evdev.discovery import EventNode, NagaConnection
from naga_control.adapters.evdev.frames import FrameParser
from naga_control.adapters.evdev.signatures import translations_for
from naga_control.adapters.evdev.source import AsyncInputSource
from naga_control.adapters.uinput.proxy import prepare_ready_proxy
from naga_control.domain.profiles import Profile
from naga_control.ports.forwarding import (
    ForwardingProxy,
    ForwardingProxyFactory,
    ForwardingProxySpec,
)
from naga_control.ports.hardware import DeviceActionSubmitter
from naga_control.ports.output import KeyboardOutput, MouseOutput
from naga_control.service.action_dispatcher import ActionDispatcher
from naga_control.service.frame_planner import FramePlanner
from naga_control.service.source_forwarding import ManagedSource
from naga_control.service.source_frame_consumer import SourceFrameConsumer
from naga_control.service.source_reader import SourceReader


class PreparedSource(AsyncInputSource, ManagedSource, Protocol):
    @property
    def node(self) -> EventNode: ...

    @property
    def forwarding_proxy_spec(self) -> ForwardingProxySpec: ...


class SourceProxyReadinessWaiter(Protocol):
    def wait_ready(self, spec: ForwardingProxySpec) -> None: ...


class RunningSourceReader(Protocol):
    def start(self) -> None: ...

    async def run(self) -> object: ...

    def stop(self) -> None: ...


class SessionDeviceActions(DeviceActionSubmitter, Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class SourceReaderFactory(Protocol):
    def __call__(
        self,
        source: PreparedSource,
        profile: Profile,
        keyboard: KeyboardOutput,
        mouse: MouseOutput,
        device_actions: DeviceActionSubmitter,
        proxy_factory: ForwardingProxyFactory,
        readiness_waiter: SourceProxyReadinessWaiter,
    ) -> RunningSourceReader: ...


def create_source_reader(
    source: PreparedSource,
    profile: Profile,
    keyboard: KeyboardOutput,
    mouse: MouseOutput,
    device_actions: DeviceActionSubmitter,
    proxy_factory: ForwardingProxyFactory,
    readiness_waiter: SourceProxyReadinessWaiter,
) -> SourceReader:
    """Build the ordered, proxy-before-grab path for one known physical node."""
    planner = FramePlanner(ActionDispatcher(profile))
    consumer = SourceFrameConsumer(
        planner,
        source,
        _proxy_preparer(source.forwarding_proxy_spec, proxy_factory, readiness_waiter),
        keyboard,
        mouse,
        device_actions,
    )
    parser = FrameParser(
        source.node, translations_for(source.node.product_id, profile.plate_layout)
    )
    return SourceReader(source, parser, consumer)


class FirstSliceSession:
    """Own mapped source tasks and shared replacement outputs for one connection."""

    def __init__(
        self,
        connection: NagaConnection,
        profile: Profile,
        keyboard: KeyboardOutput,
        mouse: MouseOutput,
        device_actions: SessionDeviceActions,
        source_opener: Callable[[EventNode], PreparedSource],
        proxy_factory: ForwardingProxyFactory,
        readiness_waiter: SourceProxyReadinessWaiter,
        reader_factory: SourceReaderFactory = create_source_reader,
    ) -> None:
        self._connection = connection
        self._profile = profile
        self._keyboard = keyboard
        self._mouse = mouse
        self._device_actions = device_actions
        self._source_opener = source_opener
        self._proxy_factory = proxy_factory
        self._readiness_waiter = readiness_waiter
        self._reader_factory = reader_factory
        self._tasks: list[asyncio.Task[object]] = []
        self._readers: list[RunningSourceReader] = []
        self._errors: list[BaseException] = []
        self._started = False
        self._stopped = False
        self._stop_task: asyncio.Task[None] | None = None

    @property
    def errors(self) -> tuple[BaseException, ...]:
        """Reader-task failures collected until the session is stopped."""
        return tuple(self._errors)

    @property
    def running(self) -> bool:
        """Whether any reader task is still reading its source."""
        return any(not task.done() for task in self._tasks)

    async def start(self) -> None:
        if self._stopped:
            raise RuntimeError("first-slice session is stopped")
        if self._started:
            raise RuntimeError("first-slice session is already active")
        self._started = True
        try:
            await self._device_actions.start()
            if self._stopped:
                raise RuntimeError("first-slice session is stopped")
            for node in _mapped_nodes(self._connection, self._profile):
                source = self._source_opener(node)
                try:
                    reader = self._reader_factory(
                        source,
                        self._profile,
                        self._keyboard,
                        self._mouse,
                        self._device_actions,
                        self._proxy_factory,
                        self._readiness_waiter,
                    )
                except BaseException:
                    with suppress(Exception):
                        source.close()
                    raise
                self._readers.append(reader)
                reader.start()
                self._tasks.append(asyncio.create_task(reader.run()))
            for task in self._tasks:
                task.add_done_callback(self._record_error)
        except BaseException:
            with suppress(Exception):
                await self.stop()
            raise

    async def stop(self) -> None:
        if self._stop_task is None:
            self._stopped = True
            # Cancel synchronously before yielding, including never-entered readers.
            for task in self._tasks:
                task.cancel()
            self._stop_task = asyncio.create_task(self._stop())
            self._stop_task.add_done_callback(
                lambda done: None if done.cancelled() else done.exception()
            )
        await asyncio.shield(self._stop_task)

    async def _stop(self) -> None:
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        first_error: Exception | None = None
        cleanup = [reader.stop for reader in self._readers]
        self._readers.clear()
        cleanup.extend(
            (
                self._keyboard.release_all,
                self._mouse.release_all,
                self._keyboard.close,
                self._mouse.close,
            )
        )
        for operation in cleanup:
            try:
                operation()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        try:
            await self._device_actions.stop()
        except Exception as exc:
            if first_error is None:
                first_error = exc
        if first_error is not None:
            raise first_error

    def release_all(self) -> None:
        """Release generated output without tearing down physical forwarding."""
        first_error: Exception | None = None
        for release in (self._keyboard.release_all, self._mouse.release_all):
            try:
                release()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error

    def _record_error(self, task: asyncio.Task[object]) -> None:
        if task.cancelled():
            return
        if (error := task.exception()) is not None:
            self._errors.append(error)
            return
        if (read_error := getattr(task.result(), "error", None)) is not None:
            self._errors.append(read_error)


def _proxy_preparer(
    spec: ForwardingProxySpec,
    factory: ForwardingProxyFactory,
    waiter: SourceProxyReadinessWaiter,
) -> Callable[[], ForwardingProxy]:
    return lambda: prepare_ready_proxy(factory, waiter, spec)


def _mapped_nodes(connection: NagaConnection, profile: Profile) -> tuple[EventNode, ...]:
    translations = translations_for(connection.product_id, profile.plate_layout)
    interfaces = {signature.interface_number for signature in translations}
    return tuple(node for node in connection.nodes if node.interface_number in interfaces)
