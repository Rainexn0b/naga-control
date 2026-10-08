"""Per-profile plate drafts kept GUI-local; no service or storage changes."""

from naga_control.domain.profiles import Configuration


class PlateDrafts:
    """Track unapplied plate choices by profile ID."""

    def __init__(self) -> None:
        self._drafts: dict[str, int] = {}

    def __bool__(self) -> bool:
        return bool(self._drafts)

    def __contains__(self, profile_id: object) -> bool:
        return profile_id in self._drafts

    def get(self, profile_id: str | None) -> int | None:
        return self._drafts.get(profile_id) if profile_id else None

    def pending_ids(self) -> list[str]:
        return sorted(self._drafts)

    def record(self, profile_id: str, configured: int | None, current: object) -> None:
        if current == configured:
            self._drafts.pop(profile_id, None)
        elif type(current) is int and current in (12, 6, 2):
            self._drafts[profile_id] = current

    def prune(self, configuration: Configuration) -> None:
        for profile_id in list(self._drafts):
            try:
                current = configuration.profile(profile_id).plate_layout
            except KeyError:
                del self._drafts[profile_id]
                continue
            if current == self._drafts[profile_id]:
                del self._drafts[profile_id]

    def clear(self) -> None:
        self._drafts.clear()
