import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from common import files, http, repositories


@pytest.mark.parametrize(
    "content,error_type",
    ((b"{broken", json.JSONDecodeError), (b"\xff", UnicodeDecodeError)),
)
def test_json_read_defaults_only_when_missing(tmp_path: Path, content, error_type) -> None:
    path = tmp_path / "history.json"
    assert files.load_json(path) == {}
    assert files.load_json(path, []) == []
    path.write_bytes(content)
    with pytest.raises(error_type):
        files.load_json(path)


@pytest.mark.parametrize("failure_stage", ("serialization", "replace"))
def test_json_write_failure_preserves_original_and_removes_temporary_file(tmp_path: Path, failure_stage: str) -> None:
    path = tmp_path / "history.json"
    files.save_json(path, {"saved": "Dữ liệu cũ"})
    original = path.read_bytes()
    if failure_stage == "serialization":
        with pytest.raises(TypeError):
            files.save_json(path, {"new": [1, object()]})
    else:
        with (
            patch.object(Path, "replace", side_effect=PermissionError("Denied")),
            pytest.raises(PermissionError),
        ):
            files.save_json(path, {"new": [1, 2]})
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]
    files.save_json(path, {"new": "Dữ liệu mới"})
    assert files.load_json(path) == {"new": "Dữ liệu mới"}
    assert path.read_bytes().endswith(b"\n")


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
        ("https://raw.githubusercontent.com/owner/repo/main/file.json", False),
        ("https://github.com/owner/repo", False),
        ("https://github.com/owner/repo/releases/download/v1/file.mpp", False),
        ("https://objects.githubusercontent.com/file", False),
        ("http://api.github.com/repos/owner/repo", False),
        ("https://notgithub.com/owner/repo/file", False),
        ("https://github.com.evil.example/owner/repo/file", False),
        ("https://notgithubusercontent.com/file", False),
    ),
)
def test_github_token_is_only_attached_to_https_api(url, authenticated, block_network) -> None:
    with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}):
        block_network.side_effect = None
        http.request(url)
    headers = block_network.call_args.args[0].headers
    assert ("Authorization" in headers) == authenticated


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
def test_gitlab_token_is_only_attached_to_gitlab_api(url, authenticated, block_network) -> None:
    with patch.dict(os.environ, {"GITLAB_TOKEN": "test-token"}):
        block_network.side_effect = None
        http.request(url)
    headers = block_network.call_args.args[0].headers
    assert headers.get("PRIVATE-TOKEN") == ("test-token" if authenticated else None)
