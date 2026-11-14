from collections.abc import Iterator
from contextlib import ExitStack
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    for name in ("GITHUB_TOKEN", "GITLAB_TOKEN"):
        monkeypatch.delenv(name, raising=False)

    def reject_request(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Unexpected network access")

    request = MagicMock(side_effect=reject_request)
    monkeypatch.setattr("urllib.request.urlopen", request)
    monkeypatch.setattr("urllib.request.OpenerDirector.open", request)
    return request


@pytest.fixture
def patch_context() -> Iterator[ExitStack]:
    with ExitStack() as context:
        yield context
