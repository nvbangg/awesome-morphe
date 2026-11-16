import os
from unittest.mock import patch

import pytest

from common import http, repositories


@pytest.mark.parametrize(
    "url,expected",
    (
        ("https://github.com/owner/repo.git", ("github", "owner/repo")),
        (
            "https://github.com/owner/repo/releases/download/v1/file.mpp",
            ("github", "owner/repo"),
        ),
        (
            "https://raw.githubusercontent.com/owner/repo/main/patches.json",
            ("github", "owner/repo"),
        ),
        ("https://gitlab.com/owner/repo", ("gitlab", "owner/repo")),
        (
            "https://gitlab.com/group/owner/repo/-/releases/v1",
            ("gitlab", "group/owner/repo"),
        ),
        (
            "https://gitlab.com/api/v4/projects/group%2Fowner%2Frepo/packages/generic/file.mpp",
            ("gitlab", "group/owner/repo"),
        ),
        (
            "https://gitlab.com/api/v4/projects/123/packages/generic/file.mpp",
            (None, None),
        ),
        ("https://notgithub.com/owner/repo/file.mpp", (None, None)),
        ("https://github.com.evil.example/owner/repo/file.mpp", (None, None)),
        ("https://example.com/github.com/owner/repo/file.mpp", (None, None)),
        ("https://example.com/?repo=https://github.com/owner/repo", (None, None)),
        ("file:///github.com/owner/repo", (None, None)),
        ("https://[invalid", (None, None)),
    ),
)
def test_repository_identity_uses_host_and_path(url, expected) -> None:
    assert repositories.parse_repo_url(url) == expected


@pytest.mark.parametrize(
    "url,authenticated",
    (
        ("https://api.github.com/repos/owner/repo", True),
        ("https://raw.githubusercontent.com/owner/repo/main/file.json", True),
        ("https://github.com/owner/repo/releases/download/v1/file.mpp", False),
        ("https://objects.githubusercontent.com/file", False),
        ("http://api.github.com/repos/owner/repo", False),
        ("https://notgithub.com/owner/repo/file", False),
        ("https://github.com.evil.example/owner/repo/file", False),
        ("https://notgithubusercontent.com/file", False),
    ),
)
def test_token_is_only_attached_to_supported_https_hosts(url, authenticated) -> None:
    with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}):
        assert ("Authorization" in http.get_auth_headers(url)) == authenticated


@pytest.mark.parametrize(
    "url,authenticated",
    (
        ("https://gitlab.com/api/v4/projects/owner%2Frepo", True),
        (
            "https://gitlab.com/api/v4/projects/123/repository/files/file/raw?ref=main",
            True,
        ),
        (
            "https://gitlab.com/api/v4/projects/123/packages/generic/bundle/1/file.mpp",
            True,
        ),
        ("https://gitlab.com/owner/repo/-/releases/v1/downloads/file.mpp", False),
        ("http://gitlab.com/api/v4/projects/123", False),
        ("https://gitlab.com.evil.example/api/v4/projects/123", False),
        ("https://api.github.com/repos/owner/repo", False),
    ),
)
def test_gitlab_token_is_only_attached_to_gitlab_api(url, authenticated) -> None:
    with patch.dict(os.environ, {"GITLAB_TOKEN": "test-token"}):
        headers = http.get_auth_headers(url)
    assert headers.get("PRIVATE-TOKEN") == ("test-token" if authenticated else None)
