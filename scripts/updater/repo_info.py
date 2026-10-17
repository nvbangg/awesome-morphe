# Copyright (c) 2026 nvbangg (github.com/nvbangg)

import contextlib
import functools
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from updater import normalize_image_url
from utils import (
    CONCURRENCY,
    UNAVAILABLE_HTTP_CODES,
    build_raw_url,
    build_repo_url,
    fetch,
    format_request_error,
    parse_repo_url,
)


@functools.cache
def fetch_gitlab_user_avatar(owner: str) -> str | None:
    with contextlib.suppress(Exception):
        if (
            data := fetch(
                f"https://gitlab.com/api/v4/users?username={owner}",
                timeout=5,
                as_json=True,
            )
        ) and isinstance(data, list):
            return data[0].get("avatar_url")
    return None


def fetch_gitlab_repo_details(repo: str) -> dict:
    query = """
    query GetProject($path: ID!) {
      project(fullPath: $path) {
        fullPath
        description
        archived
        starCount
        avatarUrl
      }
    }
    """
    payload = json.dumps({"query": query, "variables": {"path": repo}}).encode("utf-8")
    request = urllib.request.Request(
        "https://gitlab.com/api/graphql",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            project = data.get("data", {}).get("project")
            if not project:
                return {"is_404": True, "error": "Repository not found or inaccessible"}
            avatar = project.get("avatarUrl")
            if not avatar and "/" in repo:
                avatar = fetch_gitlab_user_avatar(repo.split("/")[0])

            return {
                "stars": project.get("starCount", 0),
                "description": project.get("description"),
                "avatar_url": avatar,
                "full_name": project.get("fullPath"),
                "is_archived": bool(project.get("archived")),
            }
    except Exception as error:
        return {"error": format_request_error(error)}


def fetch_repo_details(repo_url: str) -> dict:
    source, repo = parse_repo_url(repo_url)
    if not source or not repo:
        return {}

    if source == "gitlab":
        time.sleep(0.1)
        return fetch_gitlab_repo_details(repo)

    api_url = f"https://api.github.com/repos/{repo}"

    try:
        time.sleep(0.1)
        response = fetch(api_url, timeout=10, as_json=True)
        if not response or not isinstance(response, dict):
            return {}

        avatar = response.get("owner", {}).get("avatar_url")
        full_name = response.get("full_name")
        stars = response.get("stargazers_count", 0)

        return {
            "stars": stars,
            "description": response.get("description"),
            "avatar_url": avatar,
            "full_name": full_name,
            "is_archived": bool(response.get("archived")),
        }
    except Exception as error:
        details: dict[str, str | bool] = {"error": format_request_error(error)}
        if (
            isinstance(error, urllib.error.HTTPError)
            and error.code in UNAVAILABLE_HTTP_CODES
        ):
            details[f"is_{error.code}"] = True
        return details


def process(
    bundle_sources: dict,
    mode: str,
    existing_bundles: dict,
    repos_data: dict,
    custom_data: dict,
    errors: dict[str, list[str]] | None = None,
) -> dict[str, str]:
    renames = {}
    tasks = {}
    for repo, source_entry in bundle_sources.items():
        if mode == "default" and repo in existing_bundles:
            continue
        source = source_entry.get("source")
        if not source or not repo:
            continue
        tasks[repo] = build_repo_url(source, repo)

    if not tasks:
        return renames

    print(f"\nFetching repo info for {len(tasks)} bundles...")
    if mode == "default":
        for key in tasks:
            print(f"  -> {key}")

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        future_to_repo = {
            executor.submit(fetch_repo_details, url): repo
            for repo, url in tasks.items()
        }
        for future in as_completed(future_to_repo):
            repo = future_to_repo[future]
            try:
                details = future.result()
                if not details:
                    continue
                if "error" in details:
                    print(f"[-] Failed to fetch {repo}: {details['error']}")
                    if errors is not None:
                        errors["repo_metadata"].append(
                            f"{tasks[repo]}: {details['error']}"
                        )
                    continue

                source_entry = bundle_sources[repo]
                if details.get("is_archived"):
                    print(f"[-] Repository archived: {repo}")
                    if errors is not None:
                        errors["repo_metadata"].append(
                            f"{tasks[repo]}: Repository is archived"
                        )
                    source_entry["isArchived"] = True
                else:
                    source_entry.pop("isArchived", None)
                repo_url = tasks[repo]
                custom_entry = custom_data.get(repo_url, {})
                source_entry["stars"] = details.get("stars", 0) - custom_entry.get(
                    "revancedStars", 0
                )

                source_entry["repoDescription"] = details.get("description") or ""

                source = source_entry.get("source")
                image_sha = (
                    repos_data.get(repo, {}).get(source, {}).get("image")
                    if source
                    else None
                )

                if image_sha and source and repo:
                    avatar_url = build_raw_url(
                        source, repo, "main", "patches-bundle.png"
                    )
                    if avatar_url:
                        source_entry["avatarUrl"] = avatar_url
                elif details.get("avatar_url"):
                    source_entry["avatarUrl"] = normalize_image_url(
                        details["avatar_url"]
                    )
                else:
                    source_entry["avatarUrl"] = ""

                full_name = details.get("full_name")
                old_repo = source_entry.get("repo")
                if full_name and old_repo and full_name.lower() != old_repo.lower():
                    source = source_entry.get("source")
                    old_url = build_repo_url(source, old_repo)
                    new_url = build_repo_url(source, full_name)
                    print(f"[+] Rename detected: {old_repo} -> {full_name}")
                    if errors is not None:
                        errors["repo_metadata"].append(
                            f"{old_url}: Renamed to {new_url}"
                        )

                    renames[old_repo] = full_name
                    if old_repo in repos_data and full_name not in repos_data:
                        repos_data[full_name] = repos_data.pop(old_repo)
                    if old_url:
                        custom_data[old_url] = {
                            "enabled": False,
                            "note": f"Automatically disabled by GitHub Actions (Redirected/Renamed to {full_name})",
                        }
                    if new_url and new_url not in custom_data:
                        custom_data[new_url] = {
                            "note": f"Automatically added by GitHub Actions (Redirected/Renamed from {old_repo})"
                        }

                    if full_name in bundle_sources:
                        bundle_sources.pop(repo, None)
                    else:
                        source_entry["repo"] = full_name
            except Exception as error:
                print(f"[-] Failed to fetch details for {repo}: {error}")
    return renames
