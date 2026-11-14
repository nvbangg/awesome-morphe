import json
import os
import urllib.error
import urllib.parse
import urllib.request
from http.client import HTTPException
from typing import Any

from common.config import DEAD_LINK_HTTP_CODES, PROJECT_USER_AGENT


def get_auth_headers(url: str, headers: dict[str, str] | None = None) -> dict[str, str]:
    result_headers = dict(headers) if headers else {}
    parsed_url = urllib.parse.urlparse(url)
    hostname = parsed_url.hostname or ""
    is_github = any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in ("github.com", "githubusercontent.com")
    )

    if "User-Agent" not in result_headers:
        if is_github:
            result_headers["User-Agent"] = PROJECT_USER_AGENT
        else:
            result_headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

    github_token = os.environ.get("GITHUB_TOKEN")
    is_release_download = (
        "/releases/download/" in parsed_url.path
        or hostname == "objects.githubusercontent.com"
    )
    if (
        is_github
        and parsed_url.scheme == "https"
        and github_token
        and not is_release_download
        and "Authorization" not in result_headers
    ):
        result_headers["Authorization"] = f"Bearer {github_token}"

    gitlab_token = os.environ.get("GITLAB_TOKEN")
    if (
        parsed_url.scheme == "https"
        and hostname == "gitlab.com"
        and parsed_url.path.startswith("/api/v4/")
        and gitlab_token
        and not any(
            name.lower() in ("private-token", "authorization")
            for name in result_headers
        )
    ):
        result_headers["PRIVATE-TOKEN"] = gitlab_token

    return result_headers


class _AuthRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            source = urllib.parse.urlsplit(req.full_url)
            target = urllib.parse.urlsplit(redirected.full_url)
            if (source.scheme, source.netloc) != (target.scheme, target.netloc):
                redirected.remove_header("Authorization")
            if (
                target.scheme != "https"
                or target.hostname != "gitlab.com"
                or not target.path.startswith("/api/v4/")
            ):
                redirected.remove_header("Private-token")
            elif token := get_auth_headers(
                redirected.full_url, dict(redirected.header_items())
            ).get("PRIVATE-TOKEN"):
                redirected.add_header("PRIVATE-TOKEN", token)
        return redirected


HTTP_OPENER = urllib.request.build_opener(_AuthRedirectHandler())


def open_request(request: urllib.request.Request, timeout: int) -> Any:
    return HTTP_OPENER.open(request, timeout=timeout)


def fetch(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: int = 15,
    as_json: bool = False,
    binary: bool = False,
) -> Any:
    request_headers = get_auth_headers(url, headers)

    request = urllib.request.Request(url, headers=request_headers)
    with open_request(request, timeout=timeout) as response:
        content = response.read()
        if binary:
            return content
        decoded = content.decode("utf-8")
        return json.loads(decoded) if as_json else decoded


def format_request_error(error: Exception) -> str:
    if isinstance(error, urllib.error.HTTPError):
        return f"Request failed (HTTP {error.code})"
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    return f"Request failed: {reason}"


def check_link_status(url: str, timeout: int = 5) -> dict:
    try:
        headers = get_auth_headers(url)
        request = urllib.request.Request(url, headers=headers)
        with open_request(request, timeout=timeout) as response:
            final_url = response.geturl().rstrip("/")
            original_url = url.rstrip("/")
            if final_url.lower() != original_url.lower():
                return {"is_redirect": True, "final_url": final_url}
            return {"is_active": True}
    except urllib.error.HTTPError as error:
        if error.code in DEAD_LINK_HTTP_CODES:
            return {"is_dead": True, "error": f"HTTP {error.code}"}
        return {"error": f"HTTP {error.code}"}
    except (OSError, HTTPException, ValueError) as error:
        return {"error": str(error)}
