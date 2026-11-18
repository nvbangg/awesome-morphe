from collections.abc import Iterator
from contextlib import ExitStack
from unittest.mock import MagicMock

import httpx2
import pytest

from common import http
from common.constants import HTTP_TIMEOUT_SECONDS


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[MagicMock]:
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    for name in ("GITHUB_TOKEN", "GITLAB_TOKEN"):
        monkeypatch.delenv(name, raising=False)

    def reject_request(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Unexpected network access")

    request = MagicMock(side_effect=reject_request)
    request.return_value = httpx2.Response(200)
    monkeypatch.setattr("urllib.request.urlopen", reject_request)
    monkeypatch.setattr("urllib.request.OpenerDirector.open", reject_request)
    monkeypatch.setattr("httpx2.HTTPTransport.handle_request", reject_request)
    with httpx2.Client(
        transport=httpx2.MockTransport(request),
        timeout=HTTP_TIMEOUT_SECONDS,
        follow_redirects=True,
    ) as client:
        monkeypatch.setattr(http, "HTTP_CLIENT", client)
        yield request


@pytest.fixture
def http_error():
    def create_error(url: str, code: int) -> httpx2.HTTPStatusError:
        request = httpx2.Request("GET", url)
        response = httpx2.Response(code, request=request)
        return httpx2.HTTPStatusError(f"HTTP {code}", request=request, response=response)

    return create_error


@pytest.fixture
def patch_context() -> Iterator[ExitStack]:
    with ExitStack() as context:
        yield context
