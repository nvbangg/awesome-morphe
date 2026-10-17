# Copyright (c) 2026 nvbangg (github.com/nvbangg)

from http.client import HTTPException

from providers import export_provider, report_provider_warning
from utils import DISCOVER_DIR, build_repo_url, fetch, parse_repo_url

SOURCES_URL = "https://raw.githubusercontent.com/Jman-Github/Patch-Bundle-Registry/bundles/config/sources.json"
OUTPUT_PATH = DISCOVER_DIR / "jman.json"


def discover() -> str | None:
    try:
        sources_data = fetch(SOURCES_URL, timeout=30, as_json=True)
    except (OSError, HTTPException) as error:
        return report_provider_warning("jman", error, OUTPUT_PATH)
    except ValueError:
        return report_provider_warning("jman", "Invalid provider data", OUTPUT_PATH)

    if not isinstance(sources_data, dict):
        return report_provider_warning("jman", "Invalid provider data", OUTPUT_PATH)

    discovered = {}
    for value in sources_data.values():
        if not isinstance(value, dict) or value.get("disabled"):
            continue
        patches_url = value.get("patches")
        if not isinstance(patches_url, str):
            continue
        source, repo = parse_repo_url(patches_url)
        if source and repo:
            canonical_url = build_repo_url(source, repo)
            discovered[canonical_url] = {}

    return export_provider("jman", discovered, OUTPUT_PATH)


if __name__ == "__main__":
    discover()
