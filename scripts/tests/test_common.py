import os
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from unittest.mock import patch

import pytest

from common import config, files, http, repositories


def test_shared_paths_still_resolve_from_the_repository_root() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    assert repository_root == config.ROOT_DIR
    assert repository_root / "scripts" == config.SCRIPTS_DIR
    assert repository_root / "data/repos.json" == config.REPOS_JSON_PATH


def test_connection_error_is_not_retried() -> None:
    with (
        patch.object(
            http,
            "open_request",
            side_effect=urllib.error.URLError("DNS failed"),
        ) as open_url,
        pytest.raises(urllib.error.URLError),
    ):
        http.fetch("https://example.com/data")
    open_url.assert_called_once()


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


@pytest.mark.parametrize(
    "origin,url,header,authenticated",
    (
        (
            "https://gitlab.com/api/v4/projects/123",
            "https://gitlab.com/api/v4/projects/456",
            "PRIVATE-TOKEN",
            True,
        ),
        (
            "https://gitlab.com/api/v4/projects/123",
            "https://storage.example.com/file.mpp",
            "PRIVATE-TOKEN",
            False,
        ),
        (
            "https://gitlab.com/api/v4/projects/123",
            "https://gitlab.com/owner/repo/-/releases/v1/downloads/file.mpp",
            "PRIVATE-TOKEN",
            False,
        ),
        (
            "https://gitlab.com/api/v4/projects/123",
            "http://gitlab.com/api/v4/projects/123",
            "PRIVATE-TOKEN",
            False,
        ),
        (
            "https://api.github.com/repos/owner/repo",
            "https://api.github.com/repos/owner/new",
            "Authorization",
            True,
        ),
        (
            "https://api.github.com/repos/owner/repo",
            "https://storage.example.com/file",
            "Authorization",
            False,
        ),
    ),
)
def test_redirect_scopes_credentials(origin, url, header, authenticated) -> None:
    request = urllib.request.Request(
        origin, headers={header: "test-token"}, method="HEAD"
    )
    redirected = http._AuthRedirectHandler().redirect_request(
        request, None, 302, "Found", Message(), url
    )
    assert redirected is not None
    assert redirected.get_header(header.capitalize()) == (
        "test-token" if authenticated else None
    )


@pytest.mark.parametrize(
    "url,token_name,header",
    (
        ("https://api.github.com/repos/owner/repo", "GITHUB_TOKEN", "Authorization"),
        ("https://gitlab.com/api/v4/projects/123", "GITLAB_TOKEN", "Private-token"),
    ),
)
@pytest.mark.parametrize("token", (None, "test-token"))
def test_requests_use_shared_opener_with_or_without_token(
    block_network, url, token_name, header, token
) -> None:
    block_network.side_effect = None
    block_network.return_value.__enter__.return_value.read.return_value = b"{}"
    with patch.dict(os.environ, {token_name: token} if token else {}):
        assert http.fetch(url, as_json=True) == {}
    block_network.assert_called_once()
    request = block_network.call_args.args[0]
    expected = f"Bearer {token}" if token and header == "Authorization" else token
    assert request.get_header(header) == expected


def test_gitlab_release_redirect_authenticates_api_download() -> None:
    release_url = "https://gitlab.com/owner/repo/-/releases/v1/downloads/bundle.mpp"
    package_url = (
        "https://gitlab.com/api/v4/projects/123/packages/generic/bundle/1/bundle.mpp"
    )
    request = urllib.request.Request(release_url)
    with patch.dict(os.environ, {"GITLAB_TOKEN": "test-token"}):
        redirected = http._AuthRedirectHandler().redirect_request(
            request, None, 302, "Found", Message(), package_url
        )
    assert redirected is not None
    assert redirected.get_header("Private-token") == "test-token"


def test_http_error_is_not_retried(patch_context) -> None:
    error = urllib.error.HTTPError(
        "https://example.com/data", 503, "Unavailable", Message(), None
    )
    patch_context.callback(error.close)
    with (
        patch.object(http, "open_request", side_effect=error) as open_url,
        pytest.raises(urllib.error.HTTPError),
    ):
        http.fetch("https://example.com/data")
    open_url.assert_called_once()


def test_invalid_json_is_not_retried_or_reported_as_network_error() -> None:
    with patch.object(http, "open_request") as open_url:
        open_url.return_value.__enter__.return_value.read.return_value = b"{broken"
        with pytest.raises(ValueError):
            http.fetch("https://example.com/data", as_json=True)
    open_url.assert_called_once()


@pytest.mark.parametrize("result_count,collapsed", ((1, True), (10, False)))
def test_section_collapse_is_explicit_instead_of_count_based(
    result_count, collapsed
) -> None:
    content = "\n".join(f"- Result {index}" for index in range(result_count))
    section = files.format_summary_section(
        "Results", content, result_count=result_count, collapsed=collapsed
    )
    assert content in section
    if collapsed:
        assert section.count("<details>") == 1
        assert section.startswith(
            f"<details>\n<summary><h3>Results ({result_count})</h3></summary>\n\n"
        )
        assert section.endswith("\n\n</details>")
    else:
        assert section.startswith(f"### Results ({result_count})\n\n")
        assert "<details>" not in section


def test_expanded_section_keeps_its_heading_and_content() -> None:
    content = "\n".join(f"- Detail {index}" for index in range(20))
    section = files.format_summary_section(
        "Warnings", content, result_count=1, heading_level=4
    )
    assert section == f"#### Warnings (1)\n\n{content}"


def test_sections_in_separate_step_files_have_one_separator_each(
    tmp_path: Path,
) -> None:
    root = tmp_path
    paths = []
    for section_name in ("Discover", "Fetch", "Update"):
        path = root / f"{section_name}.md"
        with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(path)}):
            files.append_step_summary(f"## {section_name}:\n\n- Warning")
        paths.append(path)
        assert path.read_text(encoding="utf-8").endswith("\n\n---\n\n")
    summary = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert summary.count("\n---\n") == len(paths)


def test_empty_content_does_not_create_summary_or_separator(tmp_path: Path) -> None:
    path = tmp_path / "summary.md"
    with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(path)}):
        files.append_step_summary(" \n ")
    assert not path.exists()
