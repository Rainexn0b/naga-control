"""CLI entry for the native builder (stdlib only, isolated system Python)."""

from __future__ import annotations

from .build import main

if __name__ == "__main__":
    raise SystemExit(main())
