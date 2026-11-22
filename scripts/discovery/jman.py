# Copyright (c) 2026 nvbangg (github.com/nvbangg)

from itertools import count

import httpx2

from common.http import request
from common.models import JMAN_SOURCES
from common.repositories import build_repo_url, parse_repo_url

SOURCES_URL = "https://patch-bundles.api.jmancentral.com/graphql"
PAGE_SIZE = 100
SOURCES_QUERY = """
query MorpheSources($limit: Int!, $offset: Int!) {
  source(
    where: {enabled: {_eq: true}, bundles: {ecosystem: {_eq: "morphe"}}}
    order_by: {id: asc}
    limit: $limit
    offset: $offset
  ) { url }
}
"""


def discover() -> tuple[list[str], str | None]:
    discovered = []
    try:
        for offset in count(0, PAGE_SIZE):
            payload = request(
                SOURCES_URL,
                method="POST",
                json={"query": SOURCES_QUERY, "variables": {"limit": PAGE_SIZE, "offset": offset}},
            ).json()
            if not isinstance(payload, dict) or payload.get("errors"):
                return [], "Invalid provider data"
            sources = JMAN_SOURCES.validate_python(payload["data"]["source"])
            for value in sources:
                source, repo = parse_repo_url(value["url"])
                if canonical_url := build_repo_url(source, repo):
                    discovered.append(canonical_url)
            if len(sources) < PAGE_SIZE:
                break
    except (httpx2.HTTPError, httpx2.InvalidURL) as error:
        return [], str(error)
    except (KeyError, TypeError, ValueError):
        return [], "Invalid provider data"
    return discovered, None
