"""Shared activation gating for the unified profile dropdown."""

from naga_control.gui.models import ServiceModel
from naga_control.gui.profile_mode_view import PROFILE_MANAGEMENT_HELP, is_software_verified


def activation_gate(
    model: ServiceModel, editable: bool, selected: str | None, active: str | None
) -> tuple[bool, str]:
    """Return Activate enabled state and truthful tooltip for pending/active/gate."""
    pending = model.apply_status == "applying…"
    verified = is_software_verified(model)
    can = bool(editable) and selected != active and verified and not pending
    if can:
        return True, "Switch to the selected profile. " + PROFILE_MANAGEMENT_HELP
    if pending:
        return False, "Activation unavailable while a save is pending."
    if bool(editable) and selected == active and verified:
        return False, "Already active."
    return False, "Activation unavailable unless software mode is verified."
