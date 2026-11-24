# Copyright (c) 2026 nvbangg (github.com/nvbangg)

import html
import json
import time
from typing import Any

from common.constants import (
    DEFAULT_BRANCHES,
    DISCOVERY_JSON_PATH,
    OFFICIAL_BUNDLES_PATH,
    PACKAGE_EXAMPLE,
    PACKAGE_UNIVERSAL,
    PUBLIC_DIR,
    REPOS_JSON_PATH,
    STATE_PATH,
)
from common.files import load_json, save_json
from common.models import DISCOVERY, REPOSITORIES, UPDATE_STATE
from common.repositories import build_raw_url, build_repo_url
from common.summary import append_step_summary, format_summary_section
from updater import gplay_scrape, local_data, whats_new

BUNDLES_JSON_PATH = PUBLIC_DIR / "bundles.json"

HOT_RANK_ACTIVE_DAYS = 30
HOT_RANK_ACTIVE_MS = HOT_RANK_ACTIVE_DAYS * 24 * 60 * 60 * 1000


def run(daily: bool = False) -> int:
    repos_data = REPOSITORIES.validate_python(load_json(REPOS_JSON_PATH))
    update_state = UPDATE_STATE.validate_python(load_json(STATE_PATH, {"appHashes": {}, "history": {}}))
    existing_hashes = update_state["appHashes"]
    existing_history = update_state["history"]
    existing_bundles_data = load_json(BUNDLES_JSON_PATH)
    existing_bundles = {bundle["id"]: bundle for bundle in existing_bundles_data.get("bundles", [])}
    apps_dict = existing_bundles_data.get("store", {})
    bundle_sources: dict[str, dict[str, Any]] = {}
    total_repo_count = 0
    for repo_id, repo_metadata in repos_data.items():
        if repo_metadata.get("enabled") is False:
            continue
        source = repo_id.split(":", 1)[0]
        repo = repo_metadata["repo"]
        if any(repo_metadata.get(branch) for branch in DEFAULT_BRANCHES):
            total_repo_count += 1
        existing = existing_bundles.get(repo_id, {})
        source_entry: dict[str, Any] = {"source": source, "repo": repo}
        for field in ("appFirstSeen", "appUpdates"):
            if field in existing:
                source_entry[field] = existing[field]
        source_entry["stars"] = repo_metadata.get("stars", 0) - repo_metadata.get("revancedStars", 0)
        source_entry["repoDescription"] = repo_metadata.get("description") or ""
        source_entry["avatarUrl"] = (
            build_raw_url(source, repo, "main", "patches-bundle.png")
            if repo_metadata.get("image")
            else repo_metadata.get("avatarUrl") or ""
        )
        if repo_metadata.get("isArchived"):
            source_entry["isArchived"] = True
        bundle_sources[repo_id] = source_entry

    patch_list_errors: list[str] = []
    local_hashes = local_data.process(
        bundle_sources,
        apps_dict,
        repos_data,
        existing_hashes,
        patch_list_errors,
        existing_bundles,
    )
    successful_repo_count = len(local_hashes)
    active_apps = {package_name for bundle in bundle_sources.values() for package_name in bundle["appFirstSeen"]}
    apps_dict = {
        package_name: app_data
        for package_name, app_data in apps_dict.items()
        if package_name in active_apps or package_name == PACKAGE_UNIVERSAL
    }
    official_data = load_json(OFFICIAL_BUNDLES_PATH)
    gplay_scrape.process(apps_dict, official_data.get("store", {}), daily)
    official_ranks = {
        repo_url.lower(): bundle.get("hotRank")
        for bundle in official_data.get("bundles", [])
        if (repo := bundle.get("repo")) and (repo_url := build_repo_url(bundle.get("source"), repo))
    }
    official_ranks["https://github.com/morpheapp/morphe-patches"] = -1
    discovered = DISCOVERY.validate_python(load_json(DISCOVERY_JSON_PATH))["repositories"]
    official_repositories = {}
    official_priorities = {}
    for url, rank in official_ranks.items():
        repo_id = discovered.get(url, {}).get("id")
        if repo_id not in repos_data:
            continue
        metadata = repos_data[repo_id]
        current_url = f"https://{repo_id.split(':', 1)[0]}.com/{metadata['repo']}".lower()
        priority = (url != current_url, rank if rank is not None else float("inf"))
        if repo_id not in official_priorities or priority < official_priorities[repo_id]:
            official_priorities[repo_id] = priority
            official_repositories[repo_id] = rank
    now_ms = int(time.time() * 1000)

    def get_bundle_sort_key(repo_key: str) -> tuple:
        bundle_entry = bundle_sources[repo_key]
        repo_url = build_repo_url(bundle_entry["source"], bundle_entry["repo"])
        assert repo_url is not None
        hot_rank = official_repositories.get(repo_key)
        name = (bundle_entry.get("name") or repo_url).lower()
        repo_lower = repo_url.lower()

        if hot_rank is not None:
            return (0, hot_rank, 0, 0, name, repo_lower)

        updated_at = bundle_entry["updatedAt"]
        stars = bundle_entry["stars"]

        if (now_ms - updated_at) <= HOT_RANK_ACTIVE_MS:
            return (1, 0, -stars, -updated_at, name, repo_lower)
        return (2, 0, -updated_at, -stars, name, repo_lower)

    hot_ranked_keys = sorted(bundle_sources, key=get_bundle_sort_key)
    bundle_hot_ranks = {key: rank_index for rank_index, key in enumerate(hot_ranked_keys)}

    sorted_keys = sorted(
        bundle_sources,
        key=lambda sort_key: (
            existing_bundles.get(sort_key, {}).get("firstSeen", now_ms),
            f"https://{bundle_sources[sort_key]['source']}.com/{bundle_sources[sort_key]['repo']}".lower(),
        ),
    )
    final_bundles: list[dict[str, Any]] = []
    for key in sorted_keys:
        bundle = bundle_sources[key]
        ordered_bundle = {
            "id": key,
            "source": bundle["source"],
            "repo": bundle["repo"],
            "name": bundle["name"],
            "repoDescription": html.unescape(bundle["repoDescription"]),
            "avatarUrl": bundle["avatarUrl"],
            "hotRank": bundle_hot_ranks[key],
            "stars": bundle["stars"],
            "updatedAt": bundle["updatedAt"],
            "firstSeen": existing_bundles.get(key, {}).get("firstSeen", now_ms),
            "appFirstSeen": bundle["appFirstSeen"],
            "appUpdates": bundle["appUpdates"],
            "patches": bundle["patches"],
        }
        if key in official_repositories:
            ordered_bundle["isOfficial"] = True
        if bundle.get("isPreRelease"):
            ordered_bundle["isPreRelease"] = True
        if bundle.get("isArchived"):
            ordered_bundle["isArchived"] = True
        final_bundles.append(ordered_bundle)

    app_prerelease: dict[str, bool] = {}
    app_latest_updates: dict[str, int] = {}
    compatibilities = []
    compatibility_map = {}
    current_history: dict[str, dict[str, set[str]]] = {}
    for bundle in final_bundles:
        bundle_apps = {}
        for package_name, update_time in bundle["appUpdates"].items():
            if update_time and update_time > app_latest_updates.get(package_name, 0):
                app_latest_updates[package_name] = update_time

        is_bundle_prerelease = bool(bundle.get("isPreRelease"))
        for patch in bundle["patches"]:
            is_patch_prerelease = is_bundle_prerelease or bool(patch.get("isPreRelease"))
            compatibility_data = patch.pop("compatiblePackages", None)
            if daily:
                whats_new.collect_patch_history(bundle_apps, patch["name"], compatibility_data)
            if compatibility_data:
                compatibility_json = json.dumps(compatibility_data, sort_keys=True)
                if compatibility_json not in compatibility_map:
                    compatibility_map[compatibility_json] = len(compatibilities)
                    compatibilities.append(compatibility_data)
                patch["compatiblePackagesKey"] = compatibility_map[compatibility_json]
                for compatibility_entry in compatibility_data:
                    package_name = compatibility_entry.get("packageName")
                    if package_name:
                        app_prerelease[package_name] = app_prerelease.get(package_name, True) and is_patch_prerelease
            else:
                app_prerelease[PACKAGE_UNIVERSAL] = app_prerelease.get(PACKAGE_UNIVERSAL, True) and is_patch_prerelease
        if bundle_apps:
            current_history[bundle["id"]] = bundle_apps

    apps_store = {}
    incomplete_apps = []
    for package_name, app_data in apps_dict.items():
        app_data.setdefault("firstSeen", now_ms)
        name = app_data.get("name")
        icon_url = app_data.get("iconUrl")
        app_entry = {
            "name": name,
            "iconUrl": icon_url,
            "description": html.unescape(app_data.get("description") or ""),
            "minInstalls": app_data.get("minInstalls"),
            "category": app_data.get("category"),
            "updatedAt": app_latest_updates.get(package_name, 0),
            "firstSeen": app_data["firstSeen"],
        }
        if app_prerelease.get(package_name):
            app_entry["isPreRelease"] = True
        apps_store[package_name] = app_entry
        if package_name not in (PACKAGE_UNIVERSAL, PACKAGE_EXAMPLE):
            issues = []
            if not icon_url:
                issues.append("missing icon")
            if not name:
                issues.append("missing name")
            if issues:
                display_name = f" ({name})" if name else ""
                incomplete_apps.append(
                    (
                        bool(name),
                        f"- `{package_name}`{display_name}: {', '.join(issues)}",
                    )
                )

    save_json(
        BUNDLES_JSON_PATH,
        {
            "bundles": final_bundles,
            "compatibilities": compatibilities,
            "store": apps_store,
        },
    )
    local_data.cleanup_orphan_files(repos_data)
    print(f"Update completed. Saved {len(final_bundles)} bundles and {len(apps_store)} apps.")

    summary_sections = []
    if patch_list_errors:
        sorted_errors = sorted(patch_list_errors, key=str.lower)
        print(f"[warning] Patch list: {len(sorted_errors)} repositories with issues")
        summary_sections.append(
            format_summary_section(
                "Patch list",
                "\n".join(f"- {error}" for error in sorted_errors),
                len(sorted_errors),
            )
        )

    if incomplete_apps:
        sorted_incomplete_apps = [app_issue for _has_name, app_issue in sorted(incomplete_apps)]
        print(f"[warning] App metadata: {len(sorted_incomplete_apps)} apps missing a name or icon")
        summary_sections.append(
            format_summary_section(
                "Incomplete Apps",
                "\n".join(sorted_incomplete_apps),
                len(sorted_incomplete_apps),
            )
        )

    append_step_summary(
        "\n\n".join(
            [
                f"## 🔄 Update ({successful_repo_count}/{total_repo_count}):",
                *summary_sections,
            ]
        )
    )
    if daily:
        history_data = whats_new.generate(current_history, existing_history, final_bundles, apps_store)
        if history_data != existing_history:
            update_state["history"] = dict(sorted(history_data.items()))
    update_state["appHashes"] = dict(sorted(local_hashes.items()))
    save_json(STATE_PATH, update_state)
    return 0
