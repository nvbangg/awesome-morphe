# Copyright (c) 2026 nvbangg (github.com/nvbangg)

import httpx2

from common.constants import (
    BUNDLE_SOURCES_DIR,
    OFFICIAL_BUNDLES_PATH,
    PROJECT_USER_AGENT,
)
from common.files import save_json
from common.http import fetch
from common.models import OFFICIAL_CATALOG
from common.repositories import build_repo_url
from discovery import export_provider, report_provider_warning

BUNDLES_URL = "https://morphe-patches.software/data/bundles.json"
OUTPUT_PATH = BUNDLE_SOURCES_DIR / "official.json"
HEADERS = {
    "Referer": "https://morphe-patches.software/",
    "User-Agent": PROJECT_USER_AGENT,
}


def discover() -> str | None:
    try:
        data = fetch(BUNDLES_URL, HEADERS, as_json=True)
        catalog = OFFICIAL_CATALOG.validate_python(data)
    except (httpx2.HTTPError, httpx2.InvalidURL) as error:
        return report_provider_warning("official", error, OUTPUT_PATH)
    except ValueError:
        return report_provider_warning("official", "Invalid provider data", OUTPUT_PATH)

    discovered = {
        url: {}
        for bundle in catalog["bundles"]
        if (url := build_repo_url(bundle["source"], bundle["repo"]))
    }
    if discovered:
        save_json(OFFICIAL_BUNDLES_PATH, data)
    return export_provider("official", discovered, OUTPUT_PATH)
