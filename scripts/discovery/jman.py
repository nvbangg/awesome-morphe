# Copyright (c) 2026 nvbangg (github.com/nvbangg)

import httpx2

from common.config import BUNDLE_SOURCES_DIR
from common.http import fetch
from common.models import JMAN_SOURCES
from common.repositories import build_repo_url, parse_repo_url
from discovery import export_provider, report_provider_warning

SOURCES_URL = "https://raw.githubusercontent.com/Jman-Github/Patch-Bundle-Registry/bundles/config/sources.json"
OUTPUT_PATH = BUNDLE_SOURCES_DIR / "jman.json"


def discover() -> str | None:
    try:
        sources_data = JMAN_SOURCES.validate_python(fetch(SOURCES_URL, as_json=True))
    except httpx2.HTTPError as error:
        return report_provider_warning("jman", error, OUTPUT_PATH)
    except ValueError:
        return report_provider_warning("jman", "Invalid provider data", OUTPUT_PATH)

    discovered = {}
    for value in sources_data.values():
        if value.get("disabled"):
            continue
        source, repo = parse_repo_url(value["patches"])
        if source and repo:
            canonical_url = build_repo_url(source, repo)
            discovered[canonical_url] = {}

    return export_provider("jman", discovered, OUTPUT_PATH)
