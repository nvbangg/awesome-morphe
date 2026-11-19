# Copyright (c) 2026 nvbangg (github.com/nvbangg)

import httpx2

from common.constants import (
    OFFICIAL_BUNDLES_PATH,
    PROJECT_USER_AGENT,
)
from common.files import save_json
from common.http import request
from common.models import OFFICIAL_CATALOG
from common.repositories import build_repo_url

BUNDLES_URL = "https://morphe-patches.software/data/bundles.json"
HEADERS = {
    "Referer": "https://morphe-patches.software/",
    "User-Agent": PROJECT_USER_AGENT,
}


def discover() -> tuple[list[str], str | None]:
    try:
        data = request(BUNDLES_URL, HEADERS).json()
        catalog = OFFICIAL_CATALOG.validate_python(data)
    except (httpx2.HTTPError, httpx2.InvalidURL) as error:
        return [], str(error)
    except ValueError:
        return [], "Invalid provider data"

    discovered = [url for bundle in catalog["bundles"] if (url := build_repo_url(bundle["source"], bundle["repo"]))]
    if discovered:
        save_json(OFFICIAL_BUNDLES_PATH, data)
    return discovered, None
