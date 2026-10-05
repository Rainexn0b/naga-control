from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    name: str
    description: str
    include_steps: list[str]  # by step name


_CI_STEPS = ["Compile", "Ruff", "Ruff Format", "Type Check", "Pytest"]
_FULL_STEPS = [
    *_CI_STEPS,
    "Import Validation",
    "LOC Check",
    "Repo Validation",
    "Architecture Validation",
]

PROFILES: dict[str, Profile] = {
    "quick": Profile(
        name="quick",
        description="Quick syntax, Ruff lint, and Ruff formatting checks",
        include_steps=["Compile", "Ruff", "Ruff Format"],
    ),
    "ci": Profile(
        name="ci",
        description="Standard gates: compile, Ruff, Ruff Format, Pyright, and pytest",
        include_steps=list(_CI_STEPS),
    ),
    "full": Profile(
        name="full",
        description="Standard gates plus import, LOC, repository, and architecture validation",
        include_steps=list(_FULL_STEPS),
    ),
    "debt": Profile(
        name="debt",
        description="Generic static-analysis reports without tests or packaging",
        include_steps=[
            "Import Scan",
            "Code Markers",
            "File Size",
            "LOC Check",
            "Code Hygiene",
            "Exception Transparency",
            "Dead Code",
        ],
    ),
    "release": Profile(
        name="release",
        description="Full validation plus AppImage build and smoke test",
        include_steps=[*_FULL_STEPS, "AppImage", "AppImage Smoke"],
    ),
}
