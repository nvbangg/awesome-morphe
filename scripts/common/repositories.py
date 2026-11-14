# Copyright (c) 2026 nvbangg (github.com/nvbangg)

import time
import urllib.error
import urllib.parse
from http.client import HTTPException

from common.config import UNAVAILABLE_HTTP_CODES
from common.http import fetch, format_request_error

REPOSITORY_REQUEST_DELAY_SECONDS = 0.1
REPOSITORY_REQUEST_TIMEOUT_SECONDS = 10


def parse_repo_url(repo_url: str) -> tuple[str, str] | tuple[None, None]:
    if not repo_url:
        return None, None
    try:
        parsed_url = urllib.parse.urlsplit(repo_url)
    except ValueError:
        return None, None
    if parsed_url.scheme not in ("http", "https"):
        return None, None
    path = parsed_url.path.strip("/")
    if parsed_url.hostname in ("github.com", "raw.githubusercontent.com"):
        owner, separator, repository_path = path.partition("/")
        repo = repository_path.split("/", 1)[0].removesuffix(".git")
        if owner and separator and repo:
            return "github", f"{owner}/{repo}"
    elif parsed_url.hostname == "gitlab.com":
        if path.startswith("api/v4/projects/"):
            project = urllib.parse.unquote(
                path.removeprefix("api/v4/projects/").split("/", 1)[0]
            ).strip("/")
        else:
            project = path.split("/-/", 1)[0].removesuffix(".git")
        if "/" in project and all(project.split("/")):
            return "gitlab", project
    return None, None


def build_repo_url(source: str, repo: str) -> str | None:
    return f"https://{source}.com/{repo}" if source and repo else None


def build_raw_url(source: str, repo: str, branch: str, file_path: str) -> str | None:
    if not source or not repo or not branch or not file_path:
        return None
    if source == "github":
        return f"https://raw.githubusercontent.com/{repo}/{branch}/{file_path}"
    if source == "gitlab":
        encoded_repo = urllib.parse.quote(repo, safe="")
        encoded_file = urllib.parse.quote(file_path, safe="")
        return f"https://gitlab.com/api/v4/projects/{encoded_repo}/repository/files/{encoded_file}/raw?ref={branch}"
    return None


def _request_error(error: Exception) -> dict:
    details: dict[str, str | bool] = {"error": format_request_error(error)}
    if (
        isinstance(error, urllib.error.HTTPError)
        and error.code in UNAVAILABLE_HTTP_CODES
    ):
        details[f"is_{error.code}"] = True
    return details


def fetch_repo_details(repo_url: str) -> dict:
    source, repo = parse_repo_url(repo_url)
    if not source or not repo:
        return {}

    api_url = (
        f"https://api.github.com/repos/{repo}"
        if source == "github"
        else f"https://gitlab.com/api/v4/projects/{urllib.parse.quote(repo, safe='')}"
    )

    try:
        time.sleep(REPOSITORY_REQUEST_DELAY_SECONDS)
        response = fetch(
            api_url, timeout=REPOSITORY_REQUEST_TIMEOUT_SECONDS, as_json=True
        )
        if not response or not isinstance(response, dict):
            return {}

        if source == "gitlab":
            if (
                not isinstance(response.get("path_with_namespace"), str)
                or not response["path_with_namespace"]
                or not isinstance(response.get("archived"), bool)
            ):
                return {"error": "Invalid repository data"}
            avatar = response.get("avatar_url") or (
                response.get("namespace") or {}
            ).get("avatar_url")
            if isinstance(avatar, str) and avatar.startswith("/"):
                avatar = urllib.parse.urljoin("https://gitlab.com/", avatar)
            return {
                "stars": response.get("star_count", 0),
                "description": response.get("description"),
                "avatar_url": avatar,
                "full_name": response.get("path_with_namespace"),
                "is_archived": response["archived"],
            }

        avatar = response.get("owner", {}).get("avatar_url")
        full_name = response.get("full_name")
        stars = response.get("stargazers_count", 0)

        return {
            "stars": stars,
            "description": response.get("description"),
            "avatar_url": avatar,
            "full_name": full_name,
            "is_archived": bool(response.get("archived")),
        }
    except (OSError, HTTPException, ValueError) as error:
        return _request_error(error)
