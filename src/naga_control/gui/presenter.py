"""Qt-free presentation logic driving the observable service model."""

import enum
import logging
from collections.abc import Awaitable, Callable

from naga_control.config import parse_toml
from naga_control.domain.errors import ConfigValidationError
from naga_control.gui.models import ServiceModel, parse_snapshot
from naga_control.ipc.client import (
    InvalidConfigurationError,
    NagaControlClient,
    StaleRevisionError,
    UnknownProfileError,
)

logger = logging.getLogger(__name__)

ClientOpener = Callable[[], Awaitable[NagaControlClient]]
ClientCloser = Callable[[NagaControlClient], None]


class ApplyOutcome(enum.Enum):
    """Result of a GUI-initiated write, suitable for status-bar feedback."""

    APPLIED = "applied"
    STALE = "stale-revision"
    INVALID = "invalid"
    UNREACHABLE = "unreachable"


class GuiPresenter:
    """Keep the model current and convert typed client errors to outcomes."""

    def __init__(
        self,
        model: ServiceModel,
        *,
        open_client: ClientOpener,
        close_client: ClientCloser | None = None,
    ) -> None:
        self._model = model
        self._open = open_client
        self._close = close_client
        self._client: NagaControlClient | None = None

    async def refresh(self) -> None:
        try:
            client = await self._ensure_client()
            snapshot_document = await client.snapshot_document()
            configuration_document = await client.configuration_document()
            configuration = parse_toml(configuration_document)
        except Exception as exc:
            await self._drop_client(_describe(exc))
            return
        self._model.apply_snapshot(parse_snapshot(snapshot_document))
        self._model.apply_configuration(configuration.revision, configuration_document)

    async def release_all(self) -> None:
        try:
            client = await self._ensure_client()
            await client.release_all()
        except Exception as exc:
            await self._drop_client(_describe(exc))
            return
        await self.refresh()

    async def begin_calibration(self) -> None:
        try:
            client = await self._ensure_client()
            await client.begin_calibration()
        except Exception as exc:
            await self._drop_client(_describe(exc))
            return
        await self.refresh()

    async def end_calibration(self) -> None:
        try:
            client = await self._ensure_client()
            await client.end_calibration()
        except Exception as exc:
            await self._drop_client(_describe(exc))
            return
        await self.refresh()

    async def select_profile(self, profile_id: str) -> ApplyOutcome:
        try:
            client = await self._ensure_client()
            await client.select_profile(profile_id)
        except UnknownProfileError:
            await self.refresh()
            return ApplyOutcome.INVALID
        except Exception as exc:
            await self._drop_client(_describe(exc))
            return ApplyOutcome.UNREACHABLE
        await self.refresh()
        return ApplyOutcome.APPLIED

    async def apply_configuration(self, document: str) -> ApplyOutcome:
        expected = self._model.configuration_revision
        if expected is None:
            await self.refresh()
            expected = self._model.configuration_revision
            if expected is None:
                return ApplyOutcome.UNREACHABLE
        try:
            client = await self._ensure_client()
            revision = await client.apply_configuration(expected, document)
        except StaleRevisionError:
            await self.refresh()
            return ApplyOutcome.STALE
        except (InvalidConfigurationError, ConfigValidationError):
            return ApplyOutcome.INVALID
        except Exception as exc:
            await self._drop_client(_describe(exc))
            return ApplyOutcome.UNREACHABLE
        self._model.apply_configuration(revision, document)
        return ApplyOutcome.APPLIED

    async def _ensure_client(self) -> NagaControlClient:
        if self._client is None:
            self._client = await self._open()
        return self._client

    async def _drop_client(self, reason: str) -> None:
        client, self._client = self._client, None
        if client is not None and self._close is not None:
            try:
                self._close(client)
            except Exception:
                logger.warning("failed to close service client", exc_info=True)
        self._model.mark_unreachable(reason)


def _describe(exc: Exception) -> str:
    return str(exc) or exc.__class__.__name__
