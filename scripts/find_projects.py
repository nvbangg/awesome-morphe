# Copyright (c) 2026 nvbangg (github.com/nvbangg)

import argparse
import re
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta

from utils import (
    CONCURRENCY,
    DEFAULT_BRANCHES,
    EXCLUDED_REPOS_PATH,
    NEW_PROJECTS_PATH,
    PROJECTS_DIR,
    README_REPOS_PATH,
    ROOT_DIR,
    TEMP_DIR,
    append_step_summary,
    build_raw_url,
    check_link_status,
    fetch,
    load_json,
    load_lines,
    parse_repo_url,
    save_json,
)

RAW_SEARCH_PATH = TEMP_DIR / "raw-search.json"
RAW_FILTER_PATH = TEMP_DIR / "raw-filter.json"

SEARCH_KEYWORDS = ["morphe"]
EXCLUDED_USERS = []
API_EXCLUDED_KEYWORDS = ["morpheus", "morpheme", "morphelab"]
STANDALONE_NAME_KEYWORDS = []
EXCLUDED_KEYWORDS = []

TARGET_USERS = ["MorpheApp", "rushiranpise"]

CREATED_AFTER = "2026-01-01"
CREATED_WITHIN_DAYS = None
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


def is_patch_bundle(repo: str) -> bool:
    for branch in DEFAULT_BRANCHES:
        if not (url := build_raw_url("github", repo, branch, "patches-bundle.json")):
            continue
        status = check_link_status(url, timeout=HEAD_TIMEOUT)
        if status.get("is_active"):
            return True
        if status.get("error") and not status.get("is_dead"):
            print(f"[-] Failed to check {repo} ({branch}): {status['error']}")
    return False


def has_readme(repo: str, branch: str = "main") -> bool:
    if not (url := build_raw_url("github", repo, branch, "README.md")):
        return False
    status = check_link_status(url, timeout=HEAD_TIMEOUT)
    if status.get("is_active"):
        return True
    if status.get("error") and not status.get("is_dead"):
        print(f"[-] Failed to check README for {repo} ({branch}): {status['error']}")
    return False


def is_valid_candidate(repo: dict) -> bool:
    full_name = repo.get("full_name", "")
    if is_patch_bundle(full_name):
        return False
    return has_readme(full_name, repo.get("default_branch") or "main")


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
    unique_repos = {}
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
            except Exception as error:
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

    repos_list = list(unique_repos.values())
    save_json(RAW_SEARCH_PATH, repos_list)
    print(
        f"\nSaved {len(repos_list)} raw repositories to {RAW_SEARCH_PATH.relative_to(ROOT_DIR)}\n"
    )
    return repos_list


def filter_repos(repos: list[dict] | None = None) -> list[dict]:
    if repos is None:
        if not RAW_SEARCH_PATH.exists():
            print(
                f"Raw search file not found: {RAW_SEARCH_PATH.relative_to(ROOT_DIR)}. Run with --search first."
            )
            return []
        repos = load_json(RAW_SEARCH_PATH, [])
        print(
            f"Loaded {len(repos)} repositories from {RAW_SEARCH_PATH.relative_to(ROOT_DIR)}"
        )

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

    save_json(RAW_FILTER_PATH, candidates)
    print(
        f"Saved {len(candidates)} candidates to {RAW_FILTER_PATH.relative_to(ROOT_DIR)}\n"
    )
    return candidates


def verify_and_export_repos(candidates: list[dict] | None = None) -> list[dict]:
    if candidates is None:
        if not RAW_FILTER_PATH.exists():
            print(
                f"Filtered file not found: {RAW_FILTER_PATH.relative_to(ROOT_DIR)}. Run with --filter first."
            )
            return []
        candidates = load_json(RAW_FILTER_PATH, [])
        print(
            f"Loaded {len(candidates)} candidates from {RAW_FILTER_PATH.relative_to(ROOT_DIR)}"
        )

    if not candidates:
        print("Candidate list is empty. Skipping verification.")
        return []

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
    summary_sections = [
        f"## 🔍 Find Projects\n- **Queries:**\n{query_lines}\n- **Excluded:** non-standalone morphe variants with: {excluded_keywords}\n- **New Repositories Found:** `{len(repos)}`"
    ]
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
                f"### [{repo['full_name']}]({repo['url']}) (⭐ {repo['stars']})\n- **Created:** `{repo['created_at']}` | **Updated:** `{repo['pushed_at']}`{desc}"
            )

    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    NEW_PROJECTS_PATH.write_text(
        "\n".join(repo["url"] for repo in repos) + "\n", encoding="utf-8"
    )
    append_step_summary("\n\n".join(summary_sections))

    print(
        f"Saved {len(repos)} URLs to {NEW_PROJECTS_PATH.relative_to(ROOT_DIR)} (excluded {len(candidates) - len(repos)} patch bundles or without README)"
    )
    return repos


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Find and filter standalone repositories in the Morphe ecosystem."
    )
    parser.add_argument(
        "--search",
        action="store_true",
        help="Fetch raw repositories from GitHub Search API.",
    )
    parser.add_argument(
        "--filter",
        action="store_true",
        help="Filter raw repositories by keywords and exclusion list.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify patch bundle status and export output files.",
    )

    args = parser.parse_args()

    if args.search:
        search_repos()
    elif args.filter:
        filter_repos()
    elif args.check:
        verify_and_export_repos()
    else:
        raw_repos = search_repos()
        candidates = filter_repos(raw_repos)
        verify_and_export_repos(candidates)

    return 0


if __name__ == "__main__":
    sys.exit(main())
