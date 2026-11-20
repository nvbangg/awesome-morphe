# Copyright (c) 2026 nvbangg (github.com/nvbangg)

import argparse
import html
import json
import sys
import time
from typing import Any

from dotenv import load_dotenv

from common.constants import (
    BUNDLES_DIR,
    CUSTOM_JSON_PATH,
    DATA_DIR,
    DEFAULT_BRANCHES,
    OFFICIAL_BUNDLES_PATH,
    PACKAGE_EXAMPLE,
    PACKAGE_UNIVERSAL,
    PATCHES_DIR,
    PUBLIC_DIR,
    REPOS_JSON_PATH,
    SCRIPTS_DIR,
)
from common.files import load_json, save_json
from common.http import HTTP_CLIENT
from common.models import REPOSITORIES, SOURCES, UPDATE_STATE
from common.repositories import build_raw_url, build_repo_url, parse_repo_url, record_repo_rename
from common.summary import append_step_summary, format_summary_section
from discovery import apply_source_config
from updater import gplay_scrape, local_data, whats_new

STATE_PATH = DATA_DIR / "state.json"
BUNDLES_JSON_PATH = PUBLIC_DIR / "bundles.json"

HOT_RANK_ACTIVE_DAYS = 30
HOT_RANK_ACTIVE_MS = HOT_RANK_ACTIVE_DAYS * 24 * 60 * 60 * 1000


def apply_renames(
    bundle_sources: dict, repos_data: dict, rename_data: dict[str, str]
) -> tuple[dict[str, str], dict[str, str]]:
    renames = {}
    file_renames = {}
    for old_url, metadata in list(repos_data.items()):
        new_url = metadata.get("renamedTo")
        if not new_url:
            continue
        source, _ = parse_repo_url(old_url)
        new_source, new_repo = parse_repo_url(new_url)
        if not source or source != new_source or not new_repo or new_url.lower() == old_url.lower():
            raise ValueError(f"Invalid rename: {old_url} -> {new_url}")
        new_url = build_repo_url(source, new_repo)
        assert new_url is not None
        existing_url = next((url for url in repos_data if url.lower() == new_url.lower()), None)
        if existing_url:
            new_url = existing_url
            bundle_sources.pop(old_url, None)
        else:
            file_renames[old_url] = new_url
            repos_data[new_url] = {key: value for key, value in metadata.items() if key != "renamedTo"}
            if old_url in bundle_sources:
                bundle_sources[old_url]["repo"] = new_repo
        repos_data.pop(old_url)
        record_repo_rename(rename_data, old_url, new_url)
        renames[old_url] = new_url
    return renames, file_renames


def move_renamed_files(renames: dict[str, str]) -> None:
    for old_url, new_url in renames.items():
        source, old_repo = parse_repo_url(old_url)
        _, new_repo = parse_repo_url(new_url)
        if not source or not old_repo or not new_repo:
            raise ValueError(f"Invalid rename: {old_url} -> {new_url}")
        for directory in (BUNDLES_DIR, PATCHES_DIR):
            for branch in DEFAULT_BRANCHES:
                old_file = directory / f"{source}~{old_repo.replace('/', '~')}~{branch}.json"
                new_file = directory / f"{source}~{new_repo.replace('/', '~')}~{branch}.json"
                if old_file.is_file() and not new_file.exists():
                    old_file.rename(new_file)


def main() -> int:
    load_dotenv(SCRIPTS_DIR / ".env", override=True)
    parser = argparse.ArgumentParser(description="Update Morphe patches and bundles")
    parser.add_argument("--daily", action="store_true", help="Daily update")
    parser.add_argument("--weekly", action="store_true", help="Weekly update")
    args = parser.parse_args()
    mode = "weekly" if args.weekly else "daily" if args.daily else "default"

    registry = REPOSITORIES.validate_python(
        load_json(REPOS_JSON_PATH, {"repositories": {}, "providers": {}, "renames": {}})
    )
    repos_data = registry["repositories"]
    initial_repos = {url: dict(metadata) for url, metadata in repos_data.items()}
    rename_data = registry["renames"]
    update_state = UPDATE_STATE.validate_python(load_json(STATE_PATH, {"appHashes": {}, "history": {}}))
    existing_hashes = update_state["appHashes"]
    existing_history = update_state["history"]
    custom_data = apply_source_config(repos_data, SOURCES.validate_python(load_json(CUSTOM_JSON_PATH)), rename_data)
    existing_bundles_data = load_json(BUNDLES_JSON_PATH)
    existing_bundles = {
        build_repo_url(bundle.get("source"), bundle.get("repo")): bundle
        for bundle in existing_bundles_data.get("bundles", [])
        if bundle.get("repo")
    }
    apps_dict = existing_bundles_data.get("store", {})
    bundle_sources: dict[str, dict[str, Any]] = {}
    total_repo_count = 0
    for repo_url, repo_metadata in repos_data.items():
        if repo_metadata.get("enabled") is False:
            continue
        source, repo = parse_repo_url(repo_url)
        if not source or not repo:
            continue
        if any(repo_metadata.get(branch) for branch in DEFAULT_BRANCHES):
            total_repo_count += 1
        existing = existing_bundles.get(repo_url, {})
        source_entry: dict[str, Any] = {"source": source, "repo": repo}
        for field in ("appFirstSeen", "appUpdates"):
            if field in existing:
                source_entry[field] = existing[field]
        source_entry["stars"] = repo_metadata.get("stars", 0) - custom_data.get(repo_url.lower(), {}).get(
            "revancedStars", 0
        )
        source_entry["repoDescription"] = repo_metadata.get("description") or ""
        source_entry["avatarUrl"] = (
            build_raw_url(source, repo, "main", "patches-bundle.png")
            if repo_metadata.get("image")
            else repo_metadata.get("avatarUrl") or ""
        )
        if repo_metadata.get("isArchived"):
            source_entry["isArchived"] = True
        bundle_sources[repo_url] = source_entry

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
    renames, file_renames = apply_renames(bundle_sources, repos_data, rename_data)
    active_apps = {package_name for bundle in bundle_sources.values() for package_name in bundle["appFirstSeen"]}
    apps_dict = {
        package_name: app_data
        for package_name, app_data in apps_dict.items()
        if package_name in active_apps or package_name == PACKAGE_UNIVERSAL
    }
    gplay_scrape.process(apps_dict, mode)
    official_ranks = {
        repo_url.lower(): bundle.get("hotRank")
        for bundle in load_json(OFFICIAL_BUNDLES_PATH).get("bundles", [])
        if (repo := bundle.get("repo")) and (repo_url := build_repo_url(bundle.get("source"), repo))
    }
    official_ranks["https://github.com/morpheapp/morphe-patches"] = -1
    for old_url, new_url in renames.items():
        if old_url.lower() in official_ranks:
            official_ranks.setdefault(new_url.lower(), official_ranks[old_url.lower()])

    now_ms = int(time.time() * 1000)

    def get_bundle_sort_key(repo_key: str) -> tuple:
        bundle_entry = bundle_sources[repo_key]
        repo_url = build_repo_url(bundle_entry["source"], bundle_entry["repo"])
        assert repo_url is not None
        hot_rank = official_ranks.get(repo_url.lower())
        name = (bundle_entry.get("name") or repo_key).lower()
        repo_lower = repo_key.lower()

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
            sort_key.lower(),
        ),
    )
    final_bundles: list[dict[str, Any]] = []
    for key in sorted_keys:
        bundle = bundle_sources[key]
        repo_url = build_repo_url(bundle["source"], bundle["repo"])
        assert repo_url is not None
        ordered_bundle = {
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
        if repo_url.lower() in official_ranks:
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
            if mode != "default":
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
            repo_url = build_repo_url(bundle["source"], bundle["repo"])
            assert repo_url is not None
            current_history[repo_url] = bundle_apps

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
    cleaned_hashes = {
        repo_url: local_hashes[repo_key]
        for repo_key, bundle in bundle_sources.items()
        if repo_key in local_hashes and (repo_url := build_repo_url(bundle["source"], bundle["repo"]))
    }
    history_data = dict(existing_history)
    for old_url, new_url in renames.items():
        if old_url in history_data:
            previous_history = history_data.pop(old_url)
            history_data.setdefault(new_url, previous_history)
    if renames:
        move_renamed_files(file_renames)
        registry["renames"] = dict(sorted(rename_data.items()))
    if repos_data != initial_repos or renames:
        registry["repositories"] = dict(sorted(repos_data.items(), key=lambda item: item[0].lower()))
        save_json(REPOS_JSON_PATH, registry)
    local_data.cleanup_orphan_files(repos_data)
    print(f"Update completed. Saved {len(final_bundles)} bundles and {len(apps_store)} apps.")

    summary_sections = []
    if patch_list_errors:
        sorted_errors = sorted(patch_list_errors, key=str.lower)
        print(f"Patch list: {len(sorted_errors)} repositories")
        summary_sections.append(
            format_summary_section(
                "Patch list",
                "\n".join(f"- {error}" for error in sorted_errors),
                len(sorted_errors),
                collapsed=True,
            )
        )

    if incomplete_apps:
        sorted_incomplete_apps = [app_issue for _has_name, app_issue in sorted(incomplete_apps)]
        print(f"Incomplete apps: {len(sorted_incomplete_apps)}")
        summary_sections.append(
            format_summary_section(
                "Incomplete Apps",
                "\n".join(sorted_incomplete_apps),
                len(sorted_incomplete_apps),
                collapsed=True,
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
    if mode != "default":
        history_data = whats_new.generate(current_history, history_data, final_bundles, apps_store)
    update_state["appHashes"] = dict(sorted(cleaned_hashes.items(), key=lambda item: item[0].lower()))
    if history_data != existing_history:
        update_state["history"] = dict(sorted(history_data.items(), key=lambda item: item[0].lower()))
    save_json(STATE_PATH, update_state)
    return 0


if __name__ == "__main__":
    with HTTP_CLIENT:
        sys.exit(main())
