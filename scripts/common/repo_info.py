# Copyright (c) 2026 nvbangg (github.com/nvbangg)

import contextlib
import functools
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from http.client import HTTPException

from common.utils import (
    UNAVAILABLE_HTTP_CODES,
    fetch,
    format_request_error,
    parse_repo_url,
)


def _request_error(error: Exception) -> dict:
    details: dict[str, str | bool] = {"error": format_request_error(error)}
    if (
        isinstance(error, urllib.error.HTTPError)
        and error.code in UNAVAILABLE_HTTP_CODES
    ):
        details[f"is_{error.code}"] = True
    return details


@functools.cache
def fetch_gitlab_user_avatar(owner: str) -> str | None:
    with contextlib.suppress(Exception):
        if (
            data := fetch(
                f"https://gitlab.com/api/v4/users?username={owner}",
                timeout=5,
                as_json=True,
            )
        ) and isinstance(data, list):
            return data[0].get("avatar_url")
    return None


def fetch_gitlab_repo_details(repo: str) -> dict:
    query = """
    query GetProject($path: ID!) {
      project(fullPath: $path) {
        fullPath
        description
        archived
        starCount
        avatarUrl
      }
    }
    """
    payload = json.dumps({"query": query, "variables": {"path": repo}}).encode("utf-8")
    request = urllib.request.Request(
        "https://gitlab.com/api/graphql",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            if not isinstance(data, dict):
                return {"error": "Invalid repository data"}
            if data.get("errors"):
                return {"error": "Repository query failed"}
            query_data = data.get("data")
            if not isinstance(query_data, dict) or "project" not in query_data:
                return {"error": "Invalid repository data"}
            project = query_data["project"]
            if project is None:
                return {"error": "Repository not found or inaccessible"}
            if (
                not isinstance(project, dict)
                or not isinstance(project.get("fullPath"), str)
                or not project["fullPath"]
            ):
                return {"error": "Invalid repository data"}
            avatar = project.get("avatarUrl")
            if not avatar and "/" in repo:
                avatar = fetch_gitlab_user_avatar(repo.split("/")[0])

            return {
                "stars": project.get("starCount", 0),
                "description": project.get("description"),
                "avatar_url": avatar,
                "full_name": project.get("fullPath"),
                "is_archived": bool(project.get("archived")),
            }
    except (OSError, HTTPException, ValueError) as error:
        return _request_error(error)


def fetch_repo_details(repo_url: str, *, resolve_alias: bool = False) -> dict:
    source, repo = parse_repo_url(repo_url)
    if not source or not repo:
        return {}

    if source == "gitlab" and not resolve_alias:
        time.sleep(0.1)
        return fetch_gitlab_repo_details(repo)

    api_url = (
        f"https://api.github.com/repos/{repo}"
        if source == "github"
        else f"https://gitlab.com/api/v4/projects/{urllib.parse.quote(repo, safe='')}"
    )

    try:
        time.sleep(0.1)
        response = fetch(api_url, timeout=10, as_json=True)
        if not response or not isinstance(response, dict):
            return {}

        if source == "gitlab":
            return {
                "stars": response.get("star_count", 0),
                "description": response.get("description"),
                "avatar_url": response.get("avatar_url"),
                "full_name": response.get("path_with_namespace"),
                "is_archived": bool(response.get("archived")),
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
