# Copyright (c) 2026 nvbangg (github.com/nvbangg)

import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from http.client import HTTPException

from common.utils import (
    CONCURRENCY,
    DEAD_LINK_HTTP_CODES,
    EXCLUDED_REPOS_PATH,
    NEW_PROJECTS_PATH,
    PROJECTS_DIR,
    README_REPOS_PATH,
    ROOT_DIR,
    build_raw_url,
    fetch,
    format_request_error,
    format_summary_section,
    get_auth_headers,
    load_lines,
    parse_repo_url,
)

SEARCH_KEYWORDS = ["morphe"]
EXCLUDED_USERS = []
API_EXCLUDED_KEYWORDS = ["morpheus", "morpheme", "morphelab"]
STANDALONE_NAME_KEYWORDS = []
EXCLUDED_KEYWORDS = []

TARGET_USERS = ["MorpheApp", "rushiranpise"]

CREATED_AFTER: str | None = "2026-01-01"
CREATED_WITHIN_DAYS: int | None = None
PUSHED_WITHIN_DAYS = 30

PAGE_SIZE = 100
MAX_PAGES = 10
PAGE_DELAY_SECONDS = 1
SEARCH_TIMEOUT = 15
HEAD_TIMEOUT = 5


def build_date_filters() -> list[str]:
    parts = []
    if CREATED_WITHIN_DAYS:
        created_after = (
            datetime.now(UTC) - timedelta(days=CREATED_WITHIN_DAYS)
        ).strftime("%Y-%m-%d")
        parts.append(f"created:>{created_after}")
    elif CREATED_AFTER:
        parts.append(f"created:>{CREATED_AFTER}")

    if PUSHED_WITHIN_DAYS:
        pushed_after = (
            datetime.now(UTC) - timedelta(days=PUSHED_WITHIN_DAYS)
        ).strftime("%Y-%m-%d")
        parts.append(f"pushed:>{pushed_after}")
    return parts


def build_search_query(keyword: str) -> str:
    parts = [keyword, "size:>0", "archived:false", "fork:false"]
    parts.extend(f"-user:{user}" for user in EXCLUDED_USERS)
    parts.extend(build_date_filters())
    parts.extend(f"NOT {forbidden}" for forbidden in API_EXCLUDED_KEYWORDS)
    return " ".join(parts)


def build_user_query(user: str) -> str:
    parts = [f"user:{user}", "size:>0", "archived:false", "fork:false"]
    parts.extend(build_date_filters())
    return " ".join(parts)


def _file_exists(url: str) -> bool | None:
    request = urllib.request.Request(url, headers=get_auth_headers(url), method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=HEAD_TIMEOUT):
            return True
    except urllib.error.HTTPError as error:
        if error.code in DEAD_LINK_HTTP_CODES:
            return False
        print(f"[-] Failed to check {url}: {format_request_error(error)}")
    except (OSError, HTTPException, ValueError) as error:
        print(f"[-] Failed to check {url}: {format_request_error(error)}")
    return None


def is_valid_candidate(repo: dict) -> bool:
    full_name = repo.get("full_name", "")
    metadata_url = build_raw_url("github", full_name, "main", "patches-bundle.json")
    readme_url = build_raw_url(
        "github", full_name, repo.get("default_branch") or "main", "README.md"
    )
    if not metadata_url or not readme_url:
        return False
    return _file_exists(metadata_url) is False and _file_exists(readme_url) is True


def matches_filter_criteria(repo: dict) -> bool:
    owner = repo.get("full_name", "").split("/")[0].lower()
    is_target_user = owner in {user.lower() for user in TARGET_USERS}
    if is_target_user:
        return True

    repo_name = repo.get("name", "")
    desc = repo.get("description") or ""
    combined_text = f"{repo.get('full_name', '')} {desc}".lower()

    if any(keyword.lower() in combined_text for keyword in EXCLUDED_KEYWORDS):
        return False

    if STANDALONE_NAME_KEYWORDS:
        return any(
            re.search(
                rf"(?<![a-zA-Z0-9]){re.escape(kw)}(?![a-zA-Z0-9])",
                repo_name,
                re.IGNORECASE,
            )
            for kw in STANDALONE_NAME_KEYWORDS
        )

    return True


def search_repos() -> list[dict]:
    unique_repos: dict[str, dict] = {}
    queries = [build_search_query(kw) for kw in SEARCH_KEYWORDS] + [
        build_user_query(user) for user in TARGET_USERS
    ]

    for query in queries:
        print(f"\nSearching GitHub: {query}")
        page = 1

        while True:
            encoded_query = urllib.parse.quote(query)
            url = f"https://api.github.com/search/repositories?q={encoded_query}&sort=updated&per_page={PAGE_SIZE}&page={page}"
            try:
                page_data = fetch(url, timeout=SEARCH_TIMEOUT, as_json=True)
            except (OSError, HTTPException, ValueError) as error:
                print(f"Failed to fetch page {page}: {error}")
                break

            items = page_data.get("items", []) if isinstance(page_data, dict) else []
            if not items:
                break

            total_count = page_data.get("total_count", 0)
            print(f"Fetched page {page} ({len(items)} items, total: {total_count})")

            for repo in items:
                if full_name := repo.get("full_name", "").lower():
                    unique_repos.setdefault(full_name, repo)

            if page * PAGE_SIZE >= total_count or page >= MAX_PAGES:
                break

            page += 1
            time.sleep(PAGE_DELAY_SECONDS)

    return list(unique_repos.values())


def filter_repos(repos: list[dict]) -> list[dict]:
    if not repos:
        print("Repository list is empty. Skipping filter step.")
        return []

    known_links = set(load_lines(README_REPOS_PATH)) | set(
        load_lines(EXCLUDED_REPOS_PATH)
    )
    excluded_repos = {(parse_repo_url(link)[1] or link).lower() for link in known_links}
    print(
        f"Loaded {len(excluded_repos)} known repositories ({README_REPOS_PATH.name} & {EXCLUDED_REPOS_PATH.name})"
    )

    candidates = [
        repo
        for repo in repos
        if repo.get("full_name", "").lower() not in excluded_repos
        and matches_filter_criteria(repo)
    ]
    print(
        f"Filtered {len(candidates)} candidate repositories (excluded {len(repos) - len(candidates)} repositories)."
    )

    return candidates


def verify_and_export_repos(candidates: list[dict]) -> str:
    if not candidates:
        print("Candidate list is empty. Skipping verification.")
        return format_summary_section(
            "New projects", "No new standalone repositories found.", 0
        )

    print(
        f"Checking {len(candidates)} candidates for patches-bundle.json and README...\n"
    )
    valid_repos = []
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        future_to_repo = {
            executor.submit(is_valid_candidate, repo): repo for repo in candidates
        }
        for future in as_completed(future_to_repo):
            if future.result():
                valid_repos.append(future_to_repo[future])

    repos = [
        {
            "name": repo.get("name", ""),
            "full_name": repo.get("full_name", ""),
            "stars": repo.get("stargazers_count", 0),
            "description": repo.get("description") or "",
            "created_at": (repo.get("created_at") or "")[:10],
            "pushed_at": (repo.get("pushed_at") or "")[:10],
            "url": repo.get("html_url", ""),
        }
        for repo in valid_repos
    ]
    repos.sort(
        key=lambda item: (
            item["stars"],
            item["pushed_at"],
            item["created_at"],
            item["full_name"].lower(),
        ),
        reverse=True,
    )

    queries = [build_search_query(kw) for kw in SEARCH_KEYWORDS] + [
        build_user_query(user) for user in TARGET_USERS
    ]
    query_lines = "\n".join(f"  - `{query}`" for query in queries)
    excluded_keywords = ", ".join(EXCLUDED_KEYWORDS)
    summary_sections = [f"- **Queries:**\n{query_lines}"]
    if excluded_keywords:
        summary_sections.append(f"- **Excluded keywords:** {excluded_keywords}")
    if not repos:
        summary_sections.append("- No new standalone repositories found.")
    else:
        for repo in repos:
            desc = (
                f"\n- **Description:** {repo['description']}"
                if repo["description"]
                else ""
            )
            summary_sections.append(
                f"#### [{repo['full_name']}]({repo['url']}) ({repo['stars']} stars)\n\n- **Created:** `{repo['created_at']}` | **Updated:** `{repo['pushed_at']}`{desc}"
            )

    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    NEW_PROJECTS_PATH.write_text(
        "\n".join(repo["url"] for repo in repos) + "\n", encoding="utf-8"
    )
    print(
        f"Saved {len(repos)} URLs to {NEW_PROJECTS_PATH.relative_to(ROOT_DIR)} (excluded {len(candidates) - len(repos)} patch bundles or without README)"
    )
    return format_summary_section(
        "New projects", "\n\n".join(summary_sections), len(repos)
    )


def run() -> str:
    raw_repos = search_repos()
    candidates = filter_repos(raw_repos)
    return verify_and_export_repos(candidates)
