"""GUI-only wording for saved software profiles and device-mode observations."""

from dataclasses import dataclass

from naga_control.config import parse_toml
from naga_control.domain.errors import ConfigValidationError
from naga_control.gui.models import ServiceModel, ServiceSnapshotView

SOFTWARE_PROFILE_HELP = (
    "Naga Control saved software profiles, not onboard slots. "
    "Onboard / firmware mode does not apply the selected software profile."
)
PROFILE_SELECTION_HELP = "Activate a saved software profile. " + SOFTWARE_PROFILE_HELP
PROFILE_MANAGEMENT_HELP = (
    "Choose a profile to edit; editors follow the active profile. "
    "Use Activate or the tray to switch. " + SOFTWARE_PROFILE_HELP
)
MODE_SWITCH_GATE = "Switch mode (safety validation required)"
DEVICE_MODE_HELP = (
    "Device mode is service-wide, separate from software profiles and scroll mode. "
    "Software / driver enables Naga Control remapping; Onboard / firmware uses native "
    "mouse behavior, not the selected software profile. No onboard slot upload is available. "
    "Switching remains blocked pending held-output, wake, failure and reconnect safety tests. "
    "Software-mode readiness is reported separately; this lock concerns switching safety."
)
_MODE_LABELS = {"software": "Software / driver", "firmware": "Onboard / firmware"}


def software_profile_label(display_name: str, identifier: str) -> str:
    """Show the identifier suffix; callers must use itemData IDs, not parsing."""
    return f"{display_name} ({identifier})"


def _verified_mode(model: ServiceModel) -> str | None:
    """Return verified software/firmware mode or None when not proven."""
    if not model.connection.reachable:
        return None
    snapshot = model.snapshot
    if snapshot is None or snapshot.status != "available":
        return None
    if snapshot.calibrating or snapshot.mode_error or not snapshot.mode_ready:
        return None
    if snapshot.desired_mode != snapshot.observed_mode:
        return None
    if snapshot.desired_mode not in _MODE_LABELS:
        return None
    return snapshot.desired_mode


def is_software_verified(model: ServiceModel) -> bool:
    """Software mutations need verified driver mode plus saved software policy."""
    if _verified_mode(model) != "software":
        return False
    try:
        document = model.configuration_document
        return document is not None and parse_toml(document).mode == "software"
    except ConfigValidationError:
        return False


def is_firmware_verified(model: ServiceModel) -> bool:
    """Onboard status needs verified firmware readback; owns no mutations."""
    return _verified_mode(model) == "firmware"


@dataclass(frozen=True)
class DeviceModeView:
    """Presentation only; no selectable modes, service intent, or hardware access."""

    requested: str
    observed: str
    remapping: str
    error: str | None


def device_mode_view(model: ServiceModel) -> DeviceModeView:
    """Do not treat saved policy or a retained offline snapshot as live readback."""
    snapshot = model.snapshot
    online = model.connection.reachable
    requested = snapshot.desired_mode if snapshot is not None else None
    source = ""
    if requested is None:
        try:
            document = model.configuration_document
            requested = parse_toml(document).mode if document is not None else None
        except ConfigValidationError:
            requested = None
        if requested is not None:
            source = "saved configuration"
    if not online and requested is not None:
        source = f"{source or 'last known'}; offline"
    requested_text = _MODE_LABELS.get(requested or "", "Unknown")
    if source:
        requested_text += f" ({source})"
    observed = snapshot.observed_mode if snapshot is not None and online else None
    observed_text = _MODE_LABELS.get(observed or "", "Unknown")
    if not online:
        observed_text += " (service offline)"
    error = snapshot.mode_error if snapshot is not None else None
    if error and not online:
        error = f"Last known (offline): {error}"
    return DeviceModeView(requested_text, observed_text, _remapping_status(snapshot, online), error)


def _remapping_status(snapshot: ServiceSnapshotView | None, online: bool) -> str:
    if not online:
        return "Unknown (service offline)"
    if snapshot is None:
        return "Unknown (no mode status)"
    if snapshot.calibrating:
        return "Off (calibration passthrough)"
    if snapshot.mode_error:
        return "Not ready (mode error)"
    if snapshot.status != "available":
        return f"Not ready (device {snapshot.status})"
    if snapshot.desired_mode not in _MODE_LABELS or snapshot.observed_mode not in _MODE_LABELS:
        return "Unknown (mode not verified)"
    if snapshot.desired_mode != snapshot.observed_mode:
        return "Not ready (requested/observed differ)"
    if not snapshot.mode_ready:
        return "Not ready"
    return (
        "Active (software mode verified)"
        if snapshot.observed_mode == "software"
        else "Off (onboard mode verified)"
    )
