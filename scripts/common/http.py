import json
import os
import urllib.error
import urllib.parse
import urllib.request
from http.client import HTTPException
from typing import Any

from common.config import DEAD_LINK_HTTP_CODES, HTTP_TIMEOUT_SECONDS, PROJECT_USER_AGENT


def get_auth_headers(url: str, headers: dict[str, str] | None = None) -> dict[str, str]:
    result_headers = dict(headers or {})
    parsed_url = urllib.parse.urlparse(url)
    hostname = parsed_url.hostname or ""
    is_github = any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in ("github.com", "githubusercontent.com")
    )
    is_gitlab = hostname == "gitlab.com"

    header_names = {name.lower() for name in result_headers}
    if "user-agent" not in header_names:
        result_headers["User-Agent"] = (
            PROJECT_USER_AGENT
            if is_github or is_gitlab
            else "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        )

    if parsed_url.scheme != "https" or "authorization" in header_names:
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
        and "private-token" not in header_names
        and (gitlab_token := os.environ.get("GITLAB_TOKEN"))
    ):
        result_headers["PRIVATE-TOKEN"] = gitlab_token

    return result_headers


def fetch(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: int = HTTP_TIMEOUT_SECONDS,
    as_json: bool = False,
    binary: bool = False,
) -> Any:
    request_headers = get_auth_headers(url, headers)

    request = urllib.request.Request(url, headers=request_headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content = response.read()
        if binary:
            return content
        decoded = content.decode("utf-8")
        return json.loads(decoded) if as_json else decoded


def check_link_status(url: str, timeout: int = HTTP_TIMEOUT_SECONDS) -> dict:
    try:
        headers = get_auth_headers(url)
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            final_url = response.geturl().rstrip("/")
            original_url = url.rstrip("/")
            if final_url != original_url:
                return {"is_redirect": True, "final_url": final_url}
            return {"is_active": True}
    except urllib.error.HTTPError as error:
        if error.code in DEAD_LINK_HTTP_CODES:
            return {"is_dead": True, "error": str(error)}
        return {"error": str(error)}
    except (OSError, HTTPException, ValueError) as error:
        return {"error": str(error)}
