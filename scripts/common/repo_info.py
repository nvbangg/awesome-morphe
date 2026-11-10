# Copyright (c) 2026 nvbangg (github.com/nvbangg)

import time
import urllib.error
import urllib.parse
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
        time.sleep(0.1)
        response = fetch(api_url, timeout=10, as_json=True)
        if not response or not isinstance(response, dict):
            return {}

        if source == "gitlab":
            if (
                not isinstance(response.get("path_with_namespace"), str)
                or not response["path_with_namespace"]
                or not isinstance(response.get("archived"), bool)
            ):
                return {"error": "Invalid repository data"}
            return {
                "stars": response.get("star_count", 0),
                "description": response.get("description"),
                "avatar_url": response.get("avatar_url")
                or (response.get("namespace") or {}).get("avatar_url"),
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
