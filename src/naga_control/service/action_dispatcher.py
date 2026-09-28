"""Resolve profile bindings into ordered intents without performing I/O."""

from collections.abc import Iterable
from dataclasses import dataclass

from naga_control.domain.actions import (
    MODIFIER_KEYS,
    Action,
    DeviceAction,
    DisabledAction,
    KeyAction,
    KeyComboAction,
)
from naga_control.domain.intents import (
    ActionIntent,
    DeviceActionIntent,
    KeyOutputIntent,
    MouseButtonOutputIntent,
)
from naga_control.domain.profiles import LogicalControlId, Profile


@dataclass(frozen=True, slots=True)
class DispatchResult:
    handled: bool
    intents: tuple[ActionIntent, ...] = ()
    unsafe: bool = False


class ActionDispatcher:
    """Retain the action selected on press until its matching release."""

    def __init__(self, profile: Profile) -> None:
        self._profile = profile
        self._held: dict[LogicalControlId, Action | None] = {}
        self._key_counts: dict[str, int] = {}
        self._mouse_counts: dict[str, int] = {}

    def set_profile(self, profile: Profile) -> None:
        self._profile = profile

    def dispatch(self, control_id: LogicalControlId, value: int) -> DispatchResult:
        if value not in {0, 1, 2}:
            return DispatchResult(False, self.release_all(), unsafe=True)
        if value == 1:
            if control_id in self._held:
                return DispatchResult(self._held[control_id] is not None)
            action = self._profile.bindings.action_for(control_id, self._profile.plate_layout)
            self._held[control_id] = action
            return self._result_for(action, 1)
        if control_id not in self._held:
            return DispatchResult(False)
        action = self._held[control_id]
        if value == 0:
            del self._held[control_id]
        return self._result_for(action, value)

    def release_controls(self, control_ids: Iterable[LogicalControlId]) -> tuple[ActionIntent, ...]:
        intents: list[ActionIntent] = []
        for control_id in control_ids:
            if control_id in self._held:
                action = self._held.pop(control_id)
                intents.extend(self._result_for(action, 0).intents)
        return tuple(intents)

    def release_all(self) -> tuple[ActionIntent, ...]:
        intents: list[ActionIntent] = []
        for control_id in reversed(tuple(self._held)):
            action = self._held.pop(control_id)
            intents.extend(self._result_for(action, 0).intents)
        return tuple(intents)

    def _result_for(self, action: Action | None, value: int) -> DispatchResult:
        if action is None:
            return DispatchResult(False)
        if isinstance(action, DisabledAction):
            return DispatchResult(True)
        if isinstance(action, DeviceAction):
            intents = (DeviceActionIntent(action.action),) if value == 1 else ()
            return DispatchResult(True, intents)
        if isinstance(action, KeyAction):
            return DispatchResult(True, tuple(self._key_intents(action.key, value)))
        if isinstance(action, KeyComboAction):
            return DispatchResult(True, tuple(self._combo_intents(action, value)))
        return DispatchResult(True, tuple(self._mouse_intents(action.button, value)))

    def _key_intents(self, key: str, value: int) -> list[KeyOutputIntent]:
        count = self._key_counts.get(key, 0)
        if value == 1:
            self._key_counts[key] = count + 1
            return [KeyOutputIntent(key, 1)] if count == 0 else []
        if value == 2:
            return [KeyOutputIntent(key, 2)] if count and key not in MODIFIER_KEYS else []
        return self._release_key(key, count)

    def _combo_intents(self, action: KeyComboAction, value: int) -> list[KeyOutputIntent]:
        if value == 1:
            intents = [
                intent for modifier in action.modifiers for intent in self._key_intents(modifier, 1)
            ]
            intents.extend(self._key_intents(action.key, 1))
            return intents
        if value == 2:
            return self._key_intents(action.key, 2)
        intents = self._key_intents(action.key, 0)
        for modifier in reversed(action.modifiers):
            intents.extend(self._key_intents(modifier, 0))
        return intents

    def _release_key(self, key: str, count: int) -> list[KeyOutputIntent]:
        if count <= 1:
            self._key_counts.pop(key, None)
            return [KeyOutputIntent(key, 0)] if count else []
        self._key_counts[key] = count - 1
        return []

    def _mouse_intents(self, button: str, value: int) -> list[MouseButtonOutputIntent]:
        count = self._mouse_counts.get(button, 0)
        if value == 1:
            self._mouse_counts[button] = count + 1
            return [MouseButtonOutputIntent(button, 1)] if count == 0 else []
        if value == 2:
            return []
        if count <= 1:
            self._mouse_counts.pop(button, None)
            return [MouseButtonOutputIntent(button, 0)] if count else []
        self._mouse_counts[button] = count - 1
        return []
