"""Observable callback tests for GUI service-call failure logging."""

import concurrent.futures
import logging

import pytest

from naga_control.gui.app import _log_failure  # pyright: ignore[reportPrivateUsage]


def test_cancelled_future_produces_no_log(caplog: pytest.LogCaptureFixture) -> None:
    future: concurrent.futures.Future[object] = concurrent.futures.Future()
    future.cancel()
    assert future.cancelled()
    with caplog.at_level(logging.WARNING):
        _log_failure(future)
    assert caplog.records == []


def test_successful_future_produces_no_log(caplog: pytest.LogCaptureFixture) -> None:
    future: concurrent.futures.Future[object] = concurrent.futures.Future()
    future.set_result(object())
    with caplog.at_level(logging.WARNING):
        _log_failure(future)
    assert caplog.records == []


def test_failed_future_warns_with_exception_identity(caplog: pytest.LogCaptureFixture) -> None:
    future: concurrent.futures.Future[object] = concurrent.futures.Future()
    error = RuntimeError("boom")
    future.set_exception(error)
    with caplog.at_level(logging.WARNING):
        _log_failure(future)
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelname == "WARNING"
    assert record.getMessage() == "service call failed"
    assert record.exc_info is not None
    exc_type, exc_value, _traceback = record.exc_info
    assert exc_type is RuntimeError
    assert exc_value is error
