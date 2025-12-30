import httpx
import pytest

from apps.payments.tasks import _retryable_call


class _TaskStub:
    def __init__(self) -> None:
        self.exc: Exception | None = None

    def retry(self, *, exc: Exception) -> None:
        self.exc = exc
        raise RuntimeError("retried")


def _http_status_error() -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://internal/")
    response = httpx.Response(500, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


def test_retryable_call_retries_on_http_status_error() -> None:
    task = _TaskStub()

    async def bad_call() -> None:
        raise _http_status_error()

    with pytest.raises(RuntimeError, match="retried"):
        _retryable_call(task, "status", bad_call)

    assert isinstance(task.exc, httpx.HTTPStatusError)


def test_retryable_call_retries_on_transport_error() -> None:
    task = _TaskStub()

    async def bad_call() -> None:
        raise httpx.TransportError("transport")

    with pytest.raises(RuntimeError, match="retried"):
        _retryable_call(task, "transport", bad_call)

    assert isinstance(task.exc, httpx.TransportError)
