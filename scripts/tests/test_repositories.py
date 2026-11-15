import urllib.error
from email.message import Message
from http.client import HTTPException
from unittest.mock import patch

import pytest

from common import repositories


class TestRepositoryMetadata:
    @pytest.fixture(autouse=True)
    def prepare(self, patch_context) -> None:
        self.patch_context = patch_context

    def http_error(self, code: int) -> urllib.error.HTTPError:
        error = urllib.error.HTTPError(
            "https://example.com", code, "Failed", Message(), None
        )
        self.patch_context.callback(error.close)
        return error

    @pytest.mark.parametrize("source", ("github", "gitlab"))
    @pytest.mark.parametrize("code", (401, 403, 404, 429, 451, 503))
    def test_http_errors_keep_actual_status_and_audit_flags(self, source, code) -> None:
        error = self.http_error(code)
        with patch.object(repositories, "fetch", side_effect=error):
            details = repositories.fetch_repo_details(
                f"https://{source}.com/owner/alpha"
            )
            expected = {"error": str(error)}
            if code in repositories.UNAVAILABLE_HTTP_CODES:
                expected[f"is_{code}"] = True
            assert details == expected

    @pytest.mark.parametrize("source", ("github", "gitlab"))
    @pytest.mark.parametrize(
        "error",
        (
            urllib.error.URLError("DNS lookup failed"),
            HTTPException("Connection closed"),
            ValueError("Invalid JSON"),
        ),
    )
    def test_request_error_preserves_default_message_without_fabricating_http_status(
        self,
        error: Exception,
        source: str,
    ) -> None:
        with patch.object(repositories, "fetch", side_effect=error):
            details = repositories.fetch_repo_details(
                f"https://{source}.com/owner/alpha"
            )
        assert details == {"error": str(error)}

    @pytest.mark.parametrize(
        "archived,project_avatar",
        ((False, None), (True, "https://gitlab.com/project.png")),
    )
    def test_gitlab_metadata_uses_one_rest_request(
        self, archived, project_avatar
    ) -> None:
        with patch.object(
            repositories,
            "fetch",
            return_value={
                "path_with_namespace": "group/owner/new",
                "star_count": 5,
                "description": "Example bundle",
                "archived": archived,
                "avatar_url": project_avatar,
                "namespace": {"avatar_url": "/uploads/group.png"},
            },
        ) as request:
            details = repositories.fetch_repo_details(
                "https://gitlab.com/group/owner/old"
            )
        request.assert_called_once_with(
            "https://gitlab.com/api/v4/projects/group%2Fowner%2Fold",
            as_json=True,
        )
        assert details == {
            "full_name": "group/owner/new",
            "stars": 5,
            "description": "Example bundle",
            "avatar_url": project_avatar or "https://gitlab.com/uploads/group.png",
            "is_archived": archived,
        }

    @pytest.mark.parametrize(
        "response",
        (
            {"path_with_namespace": "owner/alpha"},
            {"archived": False},
        ),
    )
    def test_gitlab_incomplete_metadata_is_rejected(self, response) -> None:
        with patch.object(repositories, "fetch", return_value=response):
            assert repositories.fetch_repo_details(
                "https://gitlab.com/owner/alpha"
            ) == {"error": "Invalid repository data"}
