# Copyright (c) 2026 nvbangg (github.com/nvbangg)

from http.client import HTTPException

from common.utils import (
    DISCOVER_DIR,
    OFFICIAL_BUNDLES_PATH,
    build_repo_url,
    fetch,
    save_json,
)
from discovery import export_provider, report_provider_warning

BUNDLES_URL = "https://morphe-patches.software/data/bundles.json"
OUTPUT_PATH = DISCOVER_DIR / "official.json"
HEADERS = {
    "Referer": "https://morphe-patches.software/",
    "User-Agent": "AwesomeMorphe/1.0 (+https://github.com/nvbangg/awesome-morphe)",
}


def discover() -> str | None:
    try:
        data = fetch(BUNDLES_URL, headers=HEADERS, timeout=30, as_json=True)
    except (OSError, HTTPException) as error:
        return report_provider_warning("official", error, OUTPUT_PATH)
    except ValueError:
        return report_provider_warning("official", "Invalid provider data", OUTPUT_PATH)

    if not isinstance(data, dict) or not isinstance(data.get("bundles"), list):
        return report_provider_warning("official", "Invalid provider data", OUTPUT_PATH)

    discovered = {
        url: {}
        for bundle in data["bundles"]
        if isinstance(bundle, dict)
        and isinstance(bundle.get("source"), str)
        and isinstance(bundle.get("repo"), str)
        and (url := build_repo_url(bundle["source"], bundle["repo"]))
    }
    if discovered:
        save_json(OFFICIAL_BUNDLES_PATH, data)
    return export_provider("official", discovered, OUTPUT_PATH)


if __name__ == "__main__":
    discover()
