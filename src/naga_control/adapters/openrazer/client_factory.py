"""Load the host OpenRazer client with actionable, sanitized prerequisites."""

from collections.abc import Callable, Iterable
from importlib import import_module
from typing import Protocol, cast

from naga_control.domain.hardware import HardwareIssue


class ManagerSnapshot(Protocol):
    @property
    def devices(self) -> Iterable[object]: ...


type ManagerFactory = Callable[[], ManagerSnapshot]


class OpenRazerPrerequisiteError(Exception):
    def __init__(self, issue: HardwareIssue) -> None:
        super().__init__(issue.message)
        self.issue = issue


def default_manager_factory() -> ManagerSnapshot:
    """Distinguish a missing client from broken imports or an incompatible API."""
    try:
        module = import_module("openrazer.client")
        manager_class = module.DeviceManager
    except ModuleNotFoundError as exc:
        if exc.name in {"openrazer", "openrazer.client"}:
            raise OpenRazerPrerequisiteError(
                HardwareIssue(
                    "openrazer_not_installed",
                    "OpenRazer is not installed or cannot be found by Naga Control "
                    "(Python client missing). Install the compatible OpenRazer driver, "
                    "daemon and Python client; the Naga Control AppImage does not include them.",
                )
            ) from exc
        raise _client_unavailable() from exc
    except (ImportError, AttributeError) as exc:
        raise _client_unavailable() from exc
    if not callable(manager_class):
        raise _client_unavailable()
    return cast(ManagerSnapshot, manager_class())


def _client_unavailable() -> OpenRazerPrerequisiteError:
    return OpenRazerPrerequisiteError(
        HardwareIssue(
            "prerequisite_unavailable",
            "OpenRazer's Python client could not be loaded or is incompatible. "
            "Repair its dependencies and install a matching driver, daemon and Python "
            "client with Naga V3 Pro support. See the OpenRazer installation guide.",
        )
    )
