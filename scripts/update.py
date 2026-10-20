# Copyright (c) 2026 nvbangg (github.com/nvbangg)

import argparse
import html
import json
import sys
import time

from common.utils import (
    BUNDLES_DIR,
    BUNDLES_JSON_PATH,
    CUSTOM_JSON_PATH,
    DEFAULT_BRANCHES,
    HASHES_PATH,
    HISTORY_PATH,
    HOT_RANK_ACTIVE_MS,
    OFFICIAL_BUNDLES_PATH,
    PACKAGE_EXAMPLE,
    PACKAGE_UNIVERSAL,
    PATCHES_DIR,
    REPOS_JSON_PATH,
    append_step_summary,
    build_raw_url,
    build_repo_url,
    format_summary_section,
    load_json,
    parse_repo_url,
    save_json,
    set_step_output,
)
from updater import gplay_scrape, local_parse, whats_new


def apply_renames(
    bundle_sources: dict, repos_data: dict, custom_data: dict
) -> tuple[dict[str, str], dict[str, str]]:
    renames = {}
    file_renames = {}
    for old_url, metadata in list(repos_data.items()):
        new_url = metadata.get("renamedTo")
        if not new_url:
            continue
        source, old_repo = parse_repo_url(old_url)
        new_source, new_repo = parse_repo_url(new_url)
        if source != new_source or not new_repo or new_url.lower() == old_url.lower():
            raise ValueError(f"Invalid rename: {old_url} -> {new_url}")
        new_url = build_repo_url(source, new_repo)
        existing_url = next(
            (url for url in repos_data if url.lower() == new_url.lower()), None
        )
        if existing_url:
            new_url = existing_url
            bundle_sources.pop(old_url, None)
        else:
            file_renames[old_url] = new_url
            repos_data[new_url] = {
                key: value for key, value in metadata.items() if key != "renamedTo"
            }
            if old_url in bundle_sources:
                bundle_sources[old_url]["repo"] = new_repo
        repos_data.pop(old_url)
        custom_data[old_url] = {
            **custom_data.get(old_url, {}),
            "enabled": False,
            "note": f"Automatically disabled by GitHub Actions (Redirected/Renamed to {new_repo})",
        }
        custom_data.setdefault(
            new_url,
            {
                "note": f"Automatically added by GitHub Actions (Redirected/Renamed from {old_repo})",
            },
        )
        renames[old_url] = new_url
    return renames, file_renames


def move_renamed_files(renames: dict[str, str]) -> None:
    for old_url, new_url in renames.items():
        source, old_repo = parse_repo_url(old_url)
        _, new_repo = parse_repo_url(new_url)
        for directory in (BUNDLES_DIR, PATCHES_DIR):
            for branch in DEFAULT_BRANCHES:
                old_file = (
                    directory / f"{source}~{old_repo.replace('/', '~')}~{branch}.json"
                )
                new_file = (
                    directory / f"{source}~{new_repo.replace('/', '~')}~{branch}.json"
                )
                if old_file.is_file() and not new_file.exists():
                    old_file.rename(new_file)


def main() -> int:
    parser = argparse.ArgumentParser(description="Update Morphe patches and bundles")
    parser.add_argument("--daily", action="store_true", help="Daily update")
    parser.add_argument("--weekly", action="store_true", help="Weekly update")
    args = parser.parse_args()
    mode = "weekly" if args.weekly else "daily" if args.daily else "default"

    repos_data = load_json(REPOS_JSON_PATH, {})
    existing_hashes = load_json(HASHES_PATH, {})
    existing_history = load_json(HISTORY_PATH, {})
    custom_data = load_json(CUSTOM_JSON_PATH, {})
    existing_bundles_data = load_json(BUNDLES_JSON_PATH, {})
    existing_bundles = {
        build_repo_url(bundle.get("source"), bundle.get("repo")): bundle
        for bundle in existing_bundles_data.get("bundles", [])
        if bundle.get("repo")
    }
    apps_dict = existing_bundles_data.get("store", {})
    bundle_sources = {}
    total_repo_count = 0
    for repo_url, repo_metadata in repos_data.items():
        source, repo = parse_repo_url(repo_url)
        if not source or not repo or not isinstance(repo_metadata, dict):
            continue
        if any(repo_metadata.get(branch) for branch in DEFAULT_BRANCHES):
            total_repo_count += 1
        existing = existing_bundles.get(repo_url, {})
        source_entry = {"source": source, "repo": repo}
        for field in ("appFirstSeen", "appUpdates"):
            if field in existing:
                source_entry[field] = existing[field]
        source_entry["stars"] = repo_metadata.get("stars", 0) - custom_data.get(
            repo_url, {}
        ).get("revancedStars", 0)
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
    local_hashes = local_parse.process(
        bundle_sources,
        apps_dict,
        repos_data,
        existing_hashes,
        patch_list_errors,
        existing_bundles,
    )
    successful_repo_count = len(local_hashes)
    renames, file_renames = apply_renames(bundle_sources, repos_data, custom_data)
    active_apps = {
        package_name
        for bundle in bundle_sources.values()
        for package_name in bundle.get("appFirstSeen", {})
    }
    apps_dict = {
        package_name: app_data
        for package_name, app_data in apps_dict.items()
        if package_name in active_apps or package_name == PACKAGE_UNIVERSAL
    }
    gplay_scrape.process(apps_dict, mode)
    official_ranks = {
        build_repo_url(bundle.get("source"), repo).lower(): bundle.get("hotRank")
        for bundle in load_json(OFFICIAL_BUNDLES_PATH, {}).get("bundles", [])
        if (repo := bundle.get("repo"))
    }
    official_ranks["https://github.com/morpheapp/morphe-patches"] = -1
    for old_url, new_url in renames.items():
        if old_url.lower() in official_ranks:
            official_ranks.setdefault(new_url.lower(), official_ranks[old_url.lower()])

    now_ms = int(time.time() * 1000)

    def get_bundle_sort_key(repo_key: str) -> tuple:
        bundle_entry = bundle_sources[repo_key]
        hot_rank = official_ranks.get(
            build_repo_url(bundle_entry["source"], bundle_entry["repo"]).lower()
        )
        name = (bundle_entry.get("name") or repo_key).lower()
        repo_lower = repo_key.lower()

        if hot_rank is not None:
            return (0, hot_rank, 0, 0, name, repo_lower)

        updated_at = bundle_entry.get("updatedAt", 0) or 0
        stars = bundle_entry.get("stars", 0) or 0

        if (now_ms - updated_at) <= HOT_RANK_ACTIVE_MS:
            return (1, 0, -stars, -updated_at, name, repo_lower)
        return (2, 0, -updated_at, -stars, name, repo_lower)

    hot_ranked_keys = sorted(bundle_sources.keys(), key=get_bundle_sort_key)
    bundle_hot_ranks = {
        key: rank_index for rank_index, key in enumerate(hot_ranked_keys)
    }

    sorted_keys = sorted(
        bundle_sources.keys(),
        key=lambda sort_key: (
            existing_bundles.get(sort_key, {}).get(
                "firstSeen", bundle_sources[sort_key].get("updatedAt", 0)
            ),
            sort_key.lower(),
        ),
    )
    final_bundles = []
    for key in sorted_keys:
        bundle = bundle_sources[key]
        is_official = (
            build_repo_url(bundle["source"], bundle["repo"]).lower() in official_ranks
        )
        ordered_bundle = {
            "source": bundle.get("source") or "",
            "repo": bundle.get("repo") or "",
            "name": bundle.get("name") or "",
            "repoDescription": html.unescape(bundle.get("repoDescription") or ""),
            "avatarUrl": bundle.get("avatarUrl") or "",
            "hotRank": bundle_hot_ranks[key],
            "stars": bundle.get("stars") or 0,
            "updatedAt": bundle.get("updatedAt") or 0,
            "firstSeen": existing_bundles.get(key, {}).get("firstSeen", now_ms),
            "appFirstSeen": bundle.get("appFirstSeen") or {},
            "appUpdates": bundle.get("appUpdates") or {},
            "patches": bundle.get("patches") or [],
        }
        if is_official:
            ordered_bundle["isOfficial"] = True
        if bundle.get("isPreRelease"):
            ordered_bundle["isPreRelease"] = True
        if bundle.get("isArchived"):
            ordered_bundle["isArchived"] = True
        final_bundles.append(ordered_bundle)

    app_patches_status: dict[str, list[bool]] = {}
    app_latest_updates: dict[str, int] = {}
    compatibilities = []
    compatibility_map = {}
    current_history = {}
    for bundle in final_bundles:
        bundle_apps = {}
        for package_name, update_time in bundle.get("appUpdates", {}).items():
            if update_time and update_time > app_latest_updates.get(package_name, 0):
                app_latest_updates[package_name] = update_time

        is_bundle_prerelease = bool(bundle.get("isPreRelease"))
        for patch in bundle.get("patches", []):
            is_patch_prerelease = is_bundle_prerelease or bool(
                patch.get("isPreRelease")
            )
            compatibility_data = patch.pop("compatiblePackages", None)
            if mode != "default":
                whats_new.collect_patch_history(
                    bundle_apps, patch["name"], compatibility_data
                )
            if compatibility_data:
                compatibility_json = json.dumps(compatibility_data, sort_keys=True)
                if compatibility_json not in compatibility_map:
                    compatibility_map[compatibility_json] = len(compatibilities)
                    compatibilities.append(compatibility_data)
                patch["compatiblePackagesKey"] = compatibility_map[compatibility_json]
                for compatibility_entry in compatibility_data:
                    package_name = compatibility_entry.get("packageName")
                    if package_name:
                        app_patches_status.setdefault(package_name, []).append(
                            is_patch_prerelease
                        )
            else:
                app_patches_status.setdefault(PACKAGE_UNIVERSAL, []).append(
                    is_patch_prerelease
                )
        if bundle_apps:
            current_history[build_repo_url(bundle["source"], bundle["repo"])] = (
                bundle_apps
            )

    apps_store = {}
    incomplete_apps = []
    for package_name, app_data in apps_dict.items():
        app_data.setdefault("firstSeen", now_ms)
        statuses = app_patches_status.get(package_name, [])
        name = app_data.get("name")
        icon_url = app_data.get("iconUrl")
        app_entry = {
            "name": name,
            "iconUrl": icon_url,
            "description": html.unescape(app_data.get("description") or ""),
            "minInstalls": app_data.get("minInstalls"),
            "category": app_data.get("category"),
            "updatedAt": app_latest_updates.get(package_name, 0),
            "firstSeen": app_data.get("firstSeen"),
        }
        if statuses and all(statuses):
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
        build_repo_url(bundle["source"], bundle["repo"]): local_hashes[repo_key]
        for repo_key, bundle in bundle_sources.items()
        if repo_key in local_hashes
    }
    save_json(
        HASHES_PATH,
        dict(sorted(cleaned_hashes.items(), key=lambda item: item[0].lower())),
    )
    history_data = dict(existing_history)
    for old_url, new_url in renames.items():
        if old_url in history_data:
            previous_history = history_data.pop(old_url)
            history_data.setdefault(new_url, previous_history)
    if renames:
        move_renamed_files(file_renames)
        save_json(
            REPOS_JSON_PATH,
            dict(sorted(repos_data.items(), key=lambda item: item[0].lower())),
        )
        save_json(CUSTOM_JSON_PATH, custom_data)
    local_parse.cleanup_orphan_files(repos_data)
    print(
        f"Update completed. Saved {len(final_bundles)} bundles and {len(apps_store)} apps."
    )

    summary_sections = []
    if patch_list_errors:
        sorted_errors = sorted(patch_list_errors, key=str.lower)
        print(f"  Patch list ({len(sorted_errors)}):")
        for error in sorted_errors:
            print(f"    - {error}")
        summary_sections.append(
            format_summary_section(
                "Patch list",
                "\n".join(f"- {error}" for error in sorted_errors),
                len(sorted_errors),
            )
        )

    if incomplete_apps:
        sorted_incomplete_apps = [
            app_issue for _has_name, app_issue in sorted(incomplete_apps)
        ]
        print(
            f"[-] Note: {len(sorted_incomplete_apps)} apps have incomplete metadata (missing icon/name):"
        )
        for app_issue in sorted_incomplete_apps:
            print(f"  {app_issue}")
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
    if mode != "default":
        history_data = whats_new.generate(
            current_history, history_data, final_bundles, apps_store
        )
    if history_data != existing_history:
        save_json(
            HISTORY_PATH,
            dict(sorted(history_data.items(), key=lambda item: item[0].lower())),
        )
    if mode != "default":
        set_step_output("success", "true")
    return 0


if __name__ == "__main__":
    sys.exit(main())
