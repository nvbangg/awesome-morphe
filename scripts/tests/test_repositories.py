from unittest.mock import patch

import httpx2
import pytest

from common import repositories


class TestRepositoryMetadata:
    @pytest.fixture(autouse=True)
    def prepare(self, http_error) -> None:
        self.http_error = http_error

    @pytest.mark.parametrize("source,code", (("github", 404), ("gitlab", 451), ("github", 503)))
    def test_repository_errors_distinguish_unavailable_from_temporary_failure(self, source, code) -> None:
        error = self.http_error("https://example.com", code)
        with patch.object(repositories, "request", side_effect=error):
            details = repositories.fetch_repo_details(f"https://{source}.com/owner/alpha")
        assert details["error"] == str(error)
        assert details.get("is_404", False) == (code == 404)
        assert details.get("is_451", False) == (code == 451)

    @pytest.mark.parametrize(
        "error",
        (httpx2.ConnectError("DNS lookup failed"), ValueError("Invalid JSON")),
    )
    def test_request_failure_does_not_mark_repository_unavailable(self, error) -> None:
        with patch.object(repositories, "request", side_effect=error):
            assert repositories.fetch_repo_details("https://github.com/owner/alpha") == {"error": str(error)}

    @pytest.mark.parametrize(
        "archived,project_avatar",
        ((False, None), (True, "https://gitlab.com/project.png")),
    )
    def test_gitlab_metadata_preserves_identity_and_resolves_avatar(self, archived, project_avatar) -> None:
        with patch.object(
            repositories,
            "request",
            return_value=httpx2.Response(
                200,
                json={
                    "id": 123,
                    "path_with_namespace": "group/owner/new",
                    "star_count": 5,
                    "description": "Example bundle",
                    "archived": archived,
                    "avatar_url": project_avatar,
                    "namespace": {"avatar_url": "/uploads/group.png"},
                },
            ),
        ) as request:
            details = repositories.fetch_repo_details("https://gitlab.com/group/owner/old")
        request.assert_called_once_with("https://gitlab.com/api/v4/projects/group%2Fowner%2Fold")
        assert details == {
            "project_id": 123,
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
        with patch.object(repositories, "request", return_value=httpx2.Response(200, json=response)):
            assert repositories.fetch_repo_details("https://gitlab.com/owner/alpha") == {
                "error": "Invalid repository data"
            }
