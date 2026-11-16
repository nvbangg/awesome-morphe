import urllib.error
from email.message import Message
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

    @pytest.mark.parametrize(
        "source,code", (("github", 404), ("gitlab", 451), ("github", 503))
    )
    def test_repository_errors_distinguish_unavailable_from_temporary_failure(
        self, source, code
    ) -> None:
        error = self.http_error(code)
        with patch.object(repositories, "fetch", side_effect=error):
            details = repositories.fetch_repo_details(
                f"https://{source}.com/owner/alpha"
            )
        assert details["error"] == str(error)
        assert details.get("is_404", False) == (code == 404)
        assert details.get("is_451", False) == (code == 451)

    @pytest.mark.parametrize(
        "error",
        (urllib.error.URLError("DNS lookup failed"), ValueError("Invalid JSON")),
    )
    def test_request_failure_does_not_mark_repository_unavailable(self, error) -> None:
        with patch.object(repositories, "fetch", side_effect=error):
            assert repositories.fetch_repo_details(
                "https://github.com/owner/alpha"
            ) == {"error": str(error)}

    @pytest.mark.parametrize(
        "archived,project_avatar",
        ((False, None), (True, "https://gitlab.com/project.png")),
    )
    def test_gitlab_metadata_preserves_identity_and_resolves_avatar(
        self, archived, project_avatar
    ) -> None:
        with patch.object(
            repositories,
            "fetch",
            return_value={
                "id": 123,
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
        with patch.object(repositories, "fetch", return_value=response):
            assert repositories.fetch_repo_details(
                "https://gitlab.com/owner/alpha"
            ) == {"error": "Invalid repository data"}
