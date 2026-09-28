"""OpenRazer-backed hardware adapter, loaded only by the service composition root."""

from naga_control.adapters.openrazer.backend import OpenRazerBackend
from naga_control.adapters.openrazer.lifecycle_monitor import OpenRazerLifecycleMonitor

__all__ = ["OpenRazerBackend", "OpenRazerLifecycleMonitor"]
