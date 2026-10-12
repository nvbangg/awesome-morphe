# Copyright (c) 2026 nvbangg (github.com/nvbangg)

from providers import export_provider
from utils import DISCOVER_DIR, build_repo_url, fetch, parse_repo_url

SOURCES_URL = "https://raw.githubusercontent.com/Jman-Github/Patch-Bundle-Registry/bundles/config/sources.json"
OUTPUT_PATH = DISCOVER_DIR / "jman.json"


def discover() -> str | None:
    try:
        sources_data = fetch(SOURCES_URL, timeout=30, as_json=True)
    except Exception as error:
        warning_message = (
            f"[jman] Failed: {error}. Kept existing sources in {OUTPUT_PATH.name}"
        )
        print(f"[-] {warning_message}")
        return warning_message

    discovered = {}
    if isinstance(sources_data, dict):
        for value in sources_data.values():
            if not isinstance(value, dict) or value.get("disabled"):
                continue
            patches_url = value.get("patches")
            source, repo = parse_repo_url(patches_url)
            if source and repo:
                canonical_url = build_repo_url(source, repo)
                discovered[canonical_url] = {}

    return export_provider("jman", discovered, OUTPUT_PATH)


if __name__ == "__main__":
    discover()
