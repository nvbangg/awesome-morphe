import os
import urllib.parse
from typing import Any

import httpx2

from common.config import DEAD_LINK_HTTP_CODES, HTTP_TIMEOUT_SECONDS, PROJECT_USER_AGENT

HTTP_CLIENT = httpx2.Client(timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=True)


def get_auth_headers(url: str, headers: dict[str, str] | None = None) -> httpx2.Headers:
    result_headers = httpx2.Headers(headers)
    parsed_url = urllib.parse.urlparse(url)
    hostname = parsed_url.hostname or ""
    is_github = any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in ("github.com", "githubusercontent.com")
    )
    is_gitlab = hostname == "gitlab.com"

    if "user-agent" not in result_headers:
        result_headers["User-Agent"] = (
            PROJECT_USER_AGENT
            if is_github or is_gitlab
            else "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        )

    if parsed_url.scheme != "https" or "authorization" in result_headers:
        return result_headers

    if (
        is_github
        and "/releases/download/" not in parsed_url.path
        and hostname != "objects.githubusercontent.com"
        and (github_token := os.environ.get("GITHUB_TOKEN"))
    ):
        result_headers["Authorization"] = f"Bearer {github_token}"
    elif (
        is_gitlab
        and parsed_url.path.startswith("/api/v4/")
        and "private-token" not in result_headers
        and (gitlab_token := os.environ.get("GITLAB_TOKEN"))
    ):
        result_headers["PRIVATE-TOKEN"] = gitlab_token

    return result_headers


def request(
    method: str, url: str, headers: dict[str, str] | None = None, **kwargs: Any
) -> httpx2.Response:
    response = HTTP_CLIENT.request(
        method, url, headers=get_auth_headers(url, headers), **kwargs
    )
    response.raise_for_status()
    return response


def fetch(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: int = HTTP_TIMEOUT_SECONDS,
    as_json: bool = False,
    binary: bool = False,
) -> Any:
    response = request("GET", url, headers, timeout=timeout)
    if binary:
        return response.content
    return response.json() if as_json else response.text


def check_link_status(url: str, timeout: int = HTTP_TIMEOUT_SECONDS) -> dict:
    try:
        response = request("GET", url, timeout=timeout)
        final_url = str(response.url).rstrip("/")
        original_url = str(httpx2.URL(url)).rstrip("/")
        if final_url != original_url:
            return {"is_redirect": True, "final_url": final_url}
        return {"is_active": True}
    except httpx2.HTTPStatusError as error:
        if error.response.status_code in DEAD_LINK_HTTP_CODES:
            return {"is_dead": True, "error": str(error)}
        return {"error": str(error), "status_code": error.response.status_code}
    except (httpx2.RequestError, httpx2.InvalidURL, ValueError) as error:
        return {"error": str(error)}
