"""Command-line entry point for read-only Naga input capture."""

import argparse
import asyncio
import json
import math
import os
import platform
import sys
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from naga_control.adapters.evdev.discovery import NagaConnection, discover_naga_connections
from naga_control.diagnostics.capture import (
    CaptureResult,
    OpenedSource,
    capture_frames,
    close_sources,
    connection_metadata,
    format_capture_error,
    format_frame,
    open_sources,
)

CAPTURE_SCHEMA_VERSION = 1


class CaptureOutputError(OSError):
    """A capture file could not be written."""

    def __init__(self, output: Path, error: OSError) -> None:
        self.output = output
        self.error_summary = format_capture_error(error)
        super().__init__(f"{output}: {type(error).__name__}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="naga-control-capture",
        description="Inspect and capture Naga V3 Pro input frames without grabbing devices.",
    )
    parser.add_argument(
        "--list", action="store_true", help="print metadata without capturing events"
    )
    parser.add_argument(
        "--duration",
        type=_positive_float,
        default=30.0,
        metavar="SECONDS",
        help="capture duration (default: 30)",
    )
    parser.add_argument(
        "--output", type=Path, metavar="FILE", help="write a versioned JSON capture"
    )
    parser.add_argument(
        "--include-identifiers",
        action="store_true",
        help="include the device serial and physical paths in output",
    )
    parser.add_argument("--plate", choices=("2", "6", "12", "unknown"), default="unknown")
    parser.add_argument("--openrazer-revision", default="unknown")
    parser.add_argument("--firmware", default="unknown")
    parser.add_argument("--driver-mode", default="unknown")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print("Capture interrupted; no JSON file was written.", file=sys.stderr)
        return 130
    except CaptureOutputError as exc:
        detail = (
            f"{exc.output}: {exc.error_summary}"
            if type(exc) is CaptureOutputError
            else format_capture_error(exc)
        )
        print(f"Capture output error: {detail}", file=sys.stderr)
        return 2
    except PermissionError as exc:
        print(f"Permission denied: {format_capture_error(exc)}", file=sys.stderr)
        print(
            "Install the scoped udev rule and refresh the login session; do not run as root.",
            file=sys.stderr,
        )
        return 2
    except OSError as exc:
        print(f"Input device error: {format_capture_error(exc)}", file=sys.stderr)
        return 2


async def run(args: argparse.Namespace) -> int:
    connections = discover_naga_connections()
    error = _connection_error(connections)
    if error is not None:
        return error

    # Close the enumeration/open race as far as practical, then validate every
    # opened descriptor against its current udev ancestry in open_sources().
    connections = discover_naga_connections()
    error = _connection_error(connections)
    if error is not None:
        return error

    connection = connections[0]
    if not connection.nodes:
        print("The Naga USB device has no initialized event nodes.", file=sys.stderr)
        return 1
    sources = open_sources(connection)
    body_failed = False
    try:
        metadata = connection_metadata(
            connection,
            sources,
            include_identifiers=args.include_identifiers,
        )
        _print_metadata(connection, sources, metadata)
        if args.list:
            if args.output is not None:
                result = CaptureResult((), "listing only")
                _write_capture(args.output, args, metadata, result)
                print(f"Wrote {args.output}")
            return 0

        print(f"Capturing complete frames for {args.duration:g} seconds. Press Ctrl+C to abort.")
        result = await capture_frames(
            sources, args.duration, lambda frame: print(format_frame(frame))
        )
        print(f"Capture ended: {result.end_reason} ({len(result.frames)} frames)")
        if args.output is not None:
            _write_capture(args.output, args, metadata, result)
            print(f"Wrote {args.output}")
        return 0
    except BaseException:
        body_failed = True
        raise
    finally:
        try:
            close_sources(sources)
        except Exception:
            # Secondary interruptions remain unsuppressed; ordinary errors do not mask the body.
            if not body_failed:
                raise


def _print_metadata(
    connection: NagaConnection,
    sources: tuple[OpenedSource, ...],
    metadata: dict[str, object],
) -> None:
    print(
        f"Razer Naga V3 Pro: {connection.transport}, {connection.vendor_id}:{connection.product_id}"
    )
    print(json.dumps(metadata, indent=2, sort_keys=True))
    print("Live event paths (not persisted):")
    for source in sources:
        print(f"  {source.source_id}: {source.node.event_path}")


def _connection_error(connections: tuple[NagaConnection, ...]) -> int | None:
    if not connections:
        print("No supported Naga V3 Pro USB connection found.", file=sys.stderr)
        return 1
    if len(connections) != 1:
        _print_connection_conflict(connections)
        return 2
    return None


def _print_connection_conflict(connections: tuple[NagaConnection, ...]) -> None:
    found = ", ".join(
        f"{item.transport} {item.vendor_id}:{item.product_id}" for item in connections
    )
    print(f"Multiple Naga USB connections found: {found}.", file=sys.stderr)
    print(
        "Disconnect all but one transport. Wired and HyperSpeed share an OpenRazer identity.",
        file=sys.stderr,
    )


def _write_capture(
    output: Path,
    args: argparse.Namespace,
    metadata: dict[str, object],
    result: CaptureResult,
) -> None:
    document = {
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "captured_at": datetime.now(UTC).isoformat(),
        "environment": {
            "kernel": platform.release(),
            "python_evdev": version("evdev"),
            "openrazer_revision": args.openrazer_revision,
            "firmware": args.firmware,
            "driver_mode": args.driver_mode,
            "desktop": _desktop_name(),
            "plate": args.plate,
        },
        "device": metadata,
        "end_reason": result.end_reason,
        "frames": [frame.as_json() for frame in result.frames],
    }
    try:
        output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:
        raise CaptureOutputError(output, exc) from exc


def _desktop_name() -> str:
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "xorg"
    return "console"


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be finite and greater than zero")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
