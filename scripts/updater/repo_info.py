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
    CUSTOM_JSON_PATH,
    HASHES_PATH,
    HISTORY_PATH,
    REPOS_JSON_PATH,
    UNAVAILABLE_HTTP_CODES,
    build_raw_url,
    build_repo_url,
    fetch,
    load_json,
    parse_repo_url,
    save_json,
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
                return {"is_404": True, "error": "404 Not Found"}
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
        return {"error": str(error)}


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
        if (
            isinstance(error, urllib.error.HTTPError)
            and error.code in UNAVAILABLE_HTTP_CODES
        ):
            if error.code == 451:
                return {"is_451": True, "error": "451 DMCA Takedown"}
            return {"is_404": True, "error": "404 Not Found"}
        return {"error": str(error)}


def process(
    bundle_sources: dict,
    mode: str,
    existing_bundles: dict,
    errors: dict[str, list[str]] | None = None,
) -> None:
    tasks = {}
    for repo, source_entry in bundle_sources.items():
        if mode == "default" and repo in existing_bundles:
            continue
        source = source_entry.get("source")
        if not source or not repo:
            continue
        tasks[repo] = build_repo_url(source, repo)

    if not tasks:
        return

    print(f"\nFetching repo info for {len(tasks)} bundles...")
    if mode == "default":
        for key in tasks:
            print(f"  -> {key}")

    custom_data = load_json(CUSTOM_JSON_PATH, {})
    repos_data = load_json(REPOS_JSON_PATH, {})
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
                if details.get("is_404") or details.get("is_451"):
                    reason = (
                        "451 DMCA Takedown"
                        if details.get("is_451")
                        else "404 Not Found"
                    )
                    print(f"[-] Excluding {repo} due to {reason}")
                    if errors is not None:
                        errors["unavailable"].append(f"{tasks[repo]}: {reason}")
                    bundle_sources.pop(repo, None)
                    continue

                if "error" in details:
                    print(f"[-] Failed to fetch {repo}: {details['error']}")
                    if errors is not None:
                        errors["warnings"].append(f"{tasks[repo]}: {details['error']}")
                    continue

                source_entry = bundle_sources[repo]
                if details.get("is_archived"):
                    print(f"[-] Repository archived: {repo}")
                    if errors is not None:
                        errors["warnings"].append(
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
                        errors["warnings"].append(f"{old_url} -> {new_url}")

                    repos_json_data = load_json(REPOS_JSON_PATH, {})
                    if old_repo in repos_json_data:
                        repos_json_data.setdefault(
                            full_name, repos_json_data.pop(old_repo)
                        )
                        save_json(REPOS_JSON_PATH, repos_json_data)

                    custom_json_data = load_json(CUSTOM_JSON_PATH, {})
                    if old_url:
                        custom_json_data[old_url] = {
                            "enabled": False,
                            "note": f"Automatically disabled by GitHub Actions (Redirected/Renamed to {full_name})",
                        }
                    if new_url and new_url not in custom_json_data:
                        custom_json_data[new_url] = {
                            "note": f"Automatically added by GitHub Actions (Redirected/Renamed from {old_repo})"
                        }
                    save_json(CUSTOM_JSON_PATH, custom_json_data)

                    history_data = load_json(HISTORY_PATH, {})
                    if old_repo in history_data:
                        history_data.setdefault(full_name, history_data.pop(old_repo))
                        sorted_history = {
                            repo_key: history_data[repo_key]
                            for repo_key in sorted(history_data.keys(), key=str.lower)
                        }
                        save_json(HISTORY_PATH, sorted_history)

                    hashes_data = load_json(HASHES_PATH, {})
                    if old_repo in hashes_data:
                        hashes_data.setdefault(full_name, hashes_data.pop(old_repo))
                        sorted_hashes = {
                            repo_key: hashes_data[repo_key]
                            for repo_key in sorted(hashes_data.keys(), key=str.lower)
                        }
                        save_json(HASHES_PATH, sorted_hashes)

                    if full_name in bundle_sources:
                        bundle_sources.pop(repo, None)
                    else:
                        source_entry["repo"] = full_name
            except Exception as error:
                print(f"[-] Failed to fetch details for {repo}: {error}")
