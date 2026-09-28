"""Pure immutable types for Naga Control configuration."""

from naga_control.domain.actions import (
    Action,
    DeviceAction,
    DisabledAction,
    KeyAction,
    KeyComboAction,
    MouseButtonAction,
)
from naga_control.domain.defaults import default_configuration
from naga_control.domain.errors import ConfigValidationError
from naga_control.domain.hardware import HardwareDpiStage, HardwareIssue, HardwareState
from naga_control.domain.profiles import (
    Binding,
    Bindings,
    Configuration,
    DpiSettings,
    DpiStage,
    LightingEffect,
    LightingSettings,
    LightingZone,
    PowerSettings,
    Profile,
    ScrollSettings,
)

__all__ = [
    "Action",
    "Binding",
    "Bindings",
    "ConfigValidationError",
    "Configuration",
    "DeviceAction",
    "DisabledAction",
    "DpiSettings",
    "DpiStage",
    "HardwareDpiStage",
    "HardwareIssue",
    "HardwareState",
    "KeyAction",
    "KeyComboAction",
    "LightingEffect",
    "LightingSettings",
    "LightingZone",
    "MouseButtonAction",
    "PowerSettings",
    "Profile",
    "ScrollSettings",
    "default_configuration",
]
