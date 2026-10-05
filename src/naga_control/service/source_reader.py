"""Own one ordered evdev reader lifecycle without per-event task creation."""

from typing import Protocol

from naga_control.adapters.evdev.frames import FrameParser, ParsedFrame
from naga_control.adapters.evdev.source import (
    AsyncInputSource,
    SourceReadResult,
    read_parsed_frames,
)


class SourceFrameSink(Protocol):
    def start(self) -> None: ...

    def consume(self, frame: ParsedFrame) -> None: ...

    def stop(self) -> None: ...


class SourceReader:
    """Run one source sequentially and always stop its forwarding lifecycle."""

    def __init__(
        self, source: AsyncInputSource, parser: FrameParser, sink: SourceFrameSink
    ) -> None:
        self._source = source
        self._parser = parser
        self._sink = sink
        self._started = False

    def start(self) -> None:
        if self._started:
            raise RuntimeError("source reader is already active")
        self._sink.start()
        self._started = True

    async def run(self) -> SourceReadResult:
        if not self._started:
            self.start()
        try:
            return await read_parsed_frames(self._source, self._parser, self._sink.consume)
        finally:
            self.stop()

    def stop(self) -> None:
        """Close a started source even if its read task never got to run."""
        if self._started:
            self._started = False
            self._sink.stop()
