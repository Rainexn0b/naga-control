"""Unprivileged native OpenRazer package builder (Debian/Fedora/openSUSE)."""

from __future__ import annotations

__all__ = ["SUPPORTED_FAMILIES"]

SUPPORTED_FAMILIES: tuple[str, ...] = ("debian", "fedora", "opensuse")
