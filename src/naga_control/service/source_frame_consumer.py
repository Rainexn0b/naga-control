"""Synchronous composition of a parsed source frame into safe output operations."""

from collections.abc import Callable

from naga_control.adapters.evdev.frames import ParsedFrame
from naga_control.ports.forwarding import ForwardingProxy
from naga_control.ports.hardware import DeviceActionSubmitter
from naga_control.ports.output import KeyboardOutput, MouseOutput
from naga_control.service.frame_planner import FramePlanner
from naga_control.service.source_forwarding import ManagedSource, SourceForwarder


class SourceFrameConsumer:
    """Keep source forwarding and generated output fail-open as one lifecycle."""

    def __init__(
        self,
        planner: FramePlanner,
        source: ManagedSource,
        prepare_proxy: Callable[[], ForwardingProxy],
        keyboard: KeyboardOutput,
        mouse: MouseOutput,
        device_actions: DeviceActionSubmitter,
    ) -> None:
        self._planner = planner
        self._keyboard = keyboard
        self._mouse = mouse
        self._device_actions = device_actions
        self._forwarder = SourceForwarder(source, prepare_proxy, self._release_outputs)
        self._failed = False

    def start(self) -> None:
        self._forwarder.start()

    def consume(self, frame: ParsedFrame) -> None:
        if self._failed:
            return
        try:
            plan = self._planner.plan(frame)
            if plan.unsafe:
                self._forwarder.forward(plan)
            for intent in plan.key_intents:
                self._keyboard.emit(intent)
            for intent in plan.mouse_button_intents:
                self._mouse.emit(intent)
            self._forwarder.forward(plan)
            for intent in plan.device_intents:
                self._device_actions.submit(intent)
        except Exception:
            self._failed = True
            self._forwarder.stop()
            raise

    def stop(self) -> None:
        self._failed = True
        self._forwarder.stop()

    def _release_outputs(self) -> None:
        self._planner.release_all()
        self._keyboard.release_all()
        self._mouse.release_all()
