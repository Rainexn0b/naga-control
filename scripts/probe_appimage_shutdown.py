"""Opt-in, hardware-free AppImage shutdown probe; see the investigation docs."""

import atexit
import mmap
import os
import signal
import socket
import sys
import time

# Map an unused bundled library so its pages are not already resident.
library = os.path.join(
    sys.prefix,
    "lib",
    f"python{sys.version_info.major}.{sys.version_info.minor}",
    "site-packages/PySide6/Qt/lib/libQt6Core.so.6",
)
with open(library, "rb") as backing:
    mapped = mmap.mmap(backing.fileno(), 0, access=mmap.ACCESS_READ)


def stop(*_args: object) -> None:
    print("SIGTERM received", flush=True)
    time.sleep(1)
    try:
        with open(sys.executable, "rb") as stream:
            print("backing read:", stream.read(1), flush=True)
    except OSError as exc:
        print("backing read failed:", repr(exc), flush=True)
    with socket.socket() as probe:
        print("socket cleanup reached", probe.fileno(), flush=True)
    mapped.madvise(mmap.MADV_DONTNEED)
    print("accessing uncached image-backed page", flush=True)
    print("mapped byte after stop:", mapped[len(mapped) // 2], flush=True)
    mapped.close()
    raise SystemExit(0)


signal.signal(signal.SIGTERM, stop)
atexit.register(lambda: print("atexit reached", flush=True))
print("READY", os.getpid(), sys.executable, flush=True)
while True:
    time.sleep(0.1)
