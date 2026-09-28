"""Ordered output and hardware intents produced by resolved button actions."""

from dataclasses import dataclass
from typing import Literal

from naga_control.domain.actions import DeviceActionToken

type KeyValue = Literal[0, 1, 2]


@dataclass(frozen=True, slots=True)
class KeyOutputIntent:
    key: str
    value: KeyValue


@dataclass(frozen=True, slots=True)
class MouseButtonOutputIntent:
    button: str
    value: Literal[0, 1]


@dataclass(frozen=True, slots=True)
class DeviceActionIntent:
    action: DeviceActionToken


type ActionIntent = KeyOutputIntent | MouseButtonOutputIntent | DeviceActionIntent
