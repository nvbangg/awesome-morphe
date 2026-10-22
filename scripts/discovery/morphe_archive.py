# Copyright (c) 2026 nvbangg (github.com/nvbangg)

import re
from http.client import HTTPException

from common.utils import BUNDLE_SOURCES_DIR, build_repo_url, fetch
from discovery import export_provider, report_provider_warning

README_URL = (
    "https://raw.githubusercontent.com/rushiforai/morphe-archive/main/README.md"
)
OUTPUT_PATH = BUNDLE_SOURCES_DIR / "morphe-archive.json"
_REPO_RE = re.compile(r"morphe\.software/add-source\?(github|gitlab)=([^)\s]+)")


def discover() -> str | None:
    try:
        content = fetch(README_URL)
    except (OSError, HTTPException, UnicodeError) as error:
        return report_provider_warning("morphe-archive", error, OUTPUT_PATH)

    discovered = {
        url: {}
        for match in _REPO_RE.finditer(content)
        if (url := build_repo_url(match.group(1), match.group(2).strip()))
        and "/" in match.group(2)
    }

    return export_provider("morphe-archive", discovered, OUTPUT_PATH)
