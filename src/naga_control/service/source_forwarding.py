"""Fail-open lifecycle for a physical source and its prepared forwarding proxy."""

from collections.abc import Callable, Collection
from typing import Protocol

from naga_control.adapters.evdev.frames import EV_SYN, SYN_REPORT
from naga_control.ports.forwarding import ForwardingProxy
from naga_control.service.frame_planner import ForwardingPlan


class ManagedSource(Protocol):
    def revalidate(self) -> None: ...

    def drain_pending_frames(self) -> None: ...

    def active_keys(self) -> Collection[int]: ...

    def grab(self) -> None: ...

    def ungrab(self) -> None: ...

    def close(self) -> None: ...


class SourceActivationError(RuntimeError):
    """The source cannot be safely proxied and must remain fail-open."""


class SourceForwarder:
    """Own one source grab only while its forwarding proxy is safe to use."""

    def __init__(
        self,
        source: ManagedSource,
        prepare_proxy: Callable[[], ForwardingProxy],
        release_generated_outputs: Callable[[], None],
    ) -> None:
        self._source = source
        self._prepare_proxy = prepare_proxy
        self._release_generated_outputs = release_generated_outputs
        self._proxy: ForwardingProxy | None = None
        self._grabbed = False
        self._active = False
        self._cleanup_error: Exception | None = None

    def start(self) -> None:
        if self._cleanup_error is not None:
            raise self._cleanup_error
        if self._active:
            raise RuntimeError("source forwarding is already active")
        try:
            self._source.revalidate()
            self._proxy = self._prepare_proxy()
            self._source.drain_pending_frames()
            self._require_no_held_keys("before grab")
            self._source.grab()
            self._grabbed = True
            self._require_no_held_keys("after grab")
            self._active = True
        except BaseException as exc:
            self._cleanup()
            if isinstance(exc, SourceActivationError) or not isinstance(exc, Exception):
                raise
            raise SourceActivationError("could not safely activate source forwarding") from exc

    def forward(self, plan: ForwardingPlan) -> None:
        if self._cleanup_error is not None:
            raise self._cleanup_error
        if not self._active or self._proxy is None:
            raise RuntimeError("source forwarding is not active")
        if plan.unsafe:
            self._cleanup()
            raise SourceActivationError("unsafe frame plan released the source grab")
        try:
            for event in plan.forwarded_events:
                if event.event_type == EV_SYN and event.code == SYN_REPORT:
                    self._proxy.flush()
                else:
                    self._proxy.write(event.event_type, event.code, event.value)
        except OSError:
            self._cleanup()
            raise

    def stop(self) -> None:
        if self._cleanup_error is not None:
            raise self._cleanup_error
        if self._active or self._grabbed or self._proxy is not None:
            self._cleanup()
            if self._cleanup_error is not None:
                raise self._cleanup_error

    def _require_no_held_keys(self, phase: str) -> None:
        if held := tuple(self._source.active_keys()):
            raise SourceActivationError(f"physical keys are held {phase}: {held}")

    def _cleanup(self) -> None:
        """Attempt every release once; cache first ordinary failure without raising."""
        if self._cleanup_error is not None:
            self._active = False
            self._grabbed = False
            self._proxy = None
            return
        self._active = False
        try:
            self._release_generated_outputs()
        except Exception as exc:
            if self._cleanup_error is None:
                self._cleanup_error = exc
        if self._grabbed:
            try:
                self._source.ungrab()
            except Exception as exc:
                if self._cleanup_error is None:
                    self._cleanup_error = exc
        self._grabbed = False
        try:
            self._source.close()
        except Exception as exc:
            if self._cleanup_error is None:
                self._cleanup_error = exc
        proxy, self._proxy = self._proxy, None
        if proxy is not None:
            try:
                proxy.close()
            except Exception as exc:
                if self._cleanup_error is None:
                    self._cleanup_error = exc
