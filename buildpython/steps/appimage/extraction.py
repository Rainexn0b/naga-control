"""Trusted unsquashfs seam; incremental bounded I/O, no shell, post-check only."""

from __future__ import annotations

import contextlib
import os
import selectors
import subprocess
import time
from pathlib import Path

from ...utils.subproc import RunResult

UNSQUASHFS = "/usr/bin/unsquashfs"
TIMEOUT = 120.0
MAX_OUTPUT = 2 * 1024 * 1024


def staging_base() -> Path:
    candidate = Path("/tmp/opencode")
    with contextlib.suppress(OSError):
        if candidate.is_dir():
            return candidate
    return Path(os.environ.get("TMPDIR", "/tmp"))


def run_trusted_extractor(fd: int, offset: int, staging: Path) -> RunResult:
    """Run fixed argv incrementally; post-check is not a security barrier."""
    args = [
        UNSQUASHFS,
        "-o",
        str(offset),
        "-d",
        str(staging),
        "-no-progress",
        "-no-xattrs",
        f"/proc/self/fd/{fd}",
    ]
    try:
        process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=(fd,),
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            cwd=str(staging.parent),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return RunResult("unsquashfs", "", f"extractor unavailable ({type(exc).__name__})", 1)
    chunks: dict[str, list[bytes]] = {"stdout": [], "stderr": []}
    assert process.stdout is not None and process.stderr is not None
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        deadline, size = time.monotonic() + TIMEOUT, 0
        failure = ""
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failure = "unsquashfs timed out"
                break
            for key, _ in selector.select(remaining):
                try:
                    data = os.read(key.fd, 65536)
                except OSError:
                    failure = "extractor pipe failed"
                    break
                size += len(data)
                if size > MAX_OUTPUT:
                    failure = "extractor output limit exceeded"
                    break
                if data:
                    chunks[str(key.data)].append(data)
                else:
                    with contextlib.suppress(OSError, ValueError, KeyError):
                        selector.unregister(key.fileobj)
            if failure:
                break
        if failure:
            with contextlib.suppress(OSError):
                process.kill()
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                process.wait(timeout=5.0)
            return RunResult("unsquashfs", "", failure, 1)
        try:
            code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            with contextlib.suppress(OSError):
                process.kill()
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                process.wait(timeout=5.0)
            return RunResult("unsquashfs", "", "unsquashfs timed out", 1)
    try:
        stdout = b"".join(chunks["stdout"]).decode("utf-8", errors="strict")
        stderr = b"".join(chunks["stderr"]).decode("utf-8", errors="strict")
    except UnicodeError:
        return RunResult("unsquashfs", "", "extractor returned non-UTF8 output", 1)
    return RunResult("unsquashfs", stdout, stderr, code)
