# Copyright (c) 2026 nvbangg (github.com/nvbangg)

import re

import httpx2

from common.http import request
from common.repositories import build_repo_url

README_URL = "https://raw.githubusercontent.com/rushiforai/morphe-archive/main/README.md"
_REPO_RE = re.compile(r"morphe\.software/add-source\?(github|gitlab)=([^)\s]+)")


def discover() -> tuple[list[str], str | None]:
    try:
        content = request(README_URL).text
    except (httpx2.HTTPError, httpx2.InvalidURL, UnicodeError) as error:
        return [], str(error)

    discovered = [
        url
        for match in _REPO_RE.finditer(content)
        if (url := build_repo_url(match.group(1), match.group(2))) and "/" in match.group(2)
    ]

    return discovered, None
