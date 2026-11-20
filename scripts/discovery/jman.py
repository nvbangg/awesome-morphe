# Copyright (c) 2026 nvbangg (github.com/nvbangg)

import httpx2

from common.http import request
from common.models import JMAN_SOURCES
from common.repositories import build_repo_url, parse_repo_url

SOURCES_URL = "https://raw.githubusercontent.com/Jman-Github/Patch-Bundle-Registry/bundles/config/sources.json"


def discover() -> tuple[list[str], str | None]:
    try:
        sources_data = JMAN_SOURCES.validate_python(request(SOURCES_URL).json())
    except (httpx2.HTTPError, httpx2.InvalidURL) as error:
        return [], str(error)
    except ValueError:
        return [], "Invalid provider data"

    discovered = []
    for value in sources_data.values():
        if value.get("disabled"):
            continue
        source, repo = parse_repo_url(value["patches"])
        if canonical_url := build_repo_url(source, repo):
            discovered.append(canonical_url)

    return discovered, None
