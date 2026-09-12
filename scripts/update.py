# Copyright (c) 2026 nvbangg (github.com/nvbangg)

import argparse
import html
import json
import sys
import time

from updater import gplay_scrape, local_parse, repo_info
from utils import (
    BUNDLES_JSON_PATH,
    OFFICIAL_BUNDLES_PATH,
    PACKAGE_EXAMPLE,
    PACKAGE_UNIVERSAL,
    REPOS_JSON_PATH,
    append_step_summary,
    load_json,
    save_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Update Morphe patches and bundles")
    parser.add_argument("--daily", action="store_true", help="Daily update")
    parser.add_argument("--weekly", action="store_true", help="Weekly update")
    args = parser.parse_args()
    mode = "weekly" if args.weekly else "daily" if args.daily else "default"

    repos_data = load_json(REPOS_JSON_PATH, {})
    existing_bundles_data = load_json(BUNDLES_JSON_PATH, {})
    existing_bundles = {
        bundle.get("repo"): bundle
        for bundle in existing_bundles_data.get("bundles", [])
        if bundle.get("repo")
    }
    apps_dict = existing_bundles_data.get("store", {})
    bundle_sources = {}
    for repo, repo_metadata in repos_data.items():
        if not isinstance(repo_metadata, dict):
            continue
        existing = existing_bundles.get(repo, {})
        source_entry = {"repo": repo}
        for field in (
            "stars",
            "avatarUrl",
            "repoDescription",
            "appFirstSeen",
            "appUpdates",
            "isArchived",
        ):
            if field in existing:
                source_entry[field] = existing[field]
        bundle_sources[repo] = source_entry

    errors: dict[str, list[str]] = {"unavailable": [], "warnings": []}
    compatibilities_list = local_parse.process(
        bundle_sources, apps_dict, errors, existing_bundles
    )
    repo_info.process(bundle_sources, mode, existing_bundles, errors)

    gplay_scrape.process(apps_dict, mode)
    official_ranks = {
        repo.lower(): bundle.get("hotRank")
        for bundle in load_json(OFFICIAL_BUNDLES_PATH, {}).get("bundles", [])
        if (repo := bundle.get("repo"))
    }
    official_ranks["morpheapp/morphe-patches"] = -1

    now_ms = int(time.time() * 1000)
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
        hot_rank = official_ranks.get(key.lower())
        ordered_bundle = {
            "source": bundle.get("source") or "",
            "repo": bundle.get("repo") or "",
            "name": bundle.get("name") or "",
            "repoDescription": html.unescape(bundle.get("repoDescription") or ""),
            "avatarUrl": bundle.get("avatarUrl") or "",
            "stars": bundle.get("stars") or 0,
            "updatedAt": bundle.get("updatedAt") or 0,
            "firstSeen": existing_bundles.get(key, {}).get("firstSeen", now_ms),
            "appFirstSeen": bundle.get("appFirstSeen") or {},
            "appUpdates": bundle.get("appUpdates") or {},
            "patches": bundle.get("patches") or [],
        }
        if hot_rank is not None:
            ordered_bundle["hotRank"] = hot_rank
        if bundle.get("isPreRelease"):
            ordered_bundle["isPreRelease"] = True
        if bundle.get("isArchived"):
            ordered_bundle["isArchived"] = True
        final_bundles.append(ordered_bundle)

    app_patches_status: dict[str, list[bool]] = {}
    app_latest_updates: dict[str, int] = {}
    reindexed_compatibilities = []
    compatibility_map = {}
    for bundle in final_bundles:
        for package_name, update_time in bundle.get("appUpdates", {}).items():
            if update_time and update_time > app_latest_updates.get(package_name, 0):
                app_latest_updates[package_name] = update_time

        is_bundle_prerelease = bool(bundle.get("isPreRelease"))
        for patch in bundle.get("patches", []):
            is_patch_prerelease = is_bundle_prerelease or bool(
                patch.get("isPreRelease")
            )
            if "compatiblePackagesKey" in patch:
                old_key = patch["compatiblePackagesKey"]
                compatibility_data = compatibilities_list[old_key]
                compatibility_json = json.dumps(compatibility_data, sort_keys=True)
                if compatibility_json in compatibility_map:
                    patch["compatiblePackagesKey"] = compatibility_map[
                        compatibility_json
                    ]
                else:
                    new_key = len(reindexed_compatibilities)
                    reindexed_compatibilities.append(compatibility_data)
                    compatibility_map[compatibility_json] = new_key
                    patch["compatiblePackagesKey"] = new_key
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
                    f"- `{package_name}`{display_name}: {', '.join(issues)}"
                )

    save_json(
        BUNDLES_JSON_PATH,
        {
            "bundles": final_bundles,
            "compatibilities": reindexed_compatibilities,
            "store": apps_store,
        },
    )
    print(
        f"Update completed. Saved {len(final_bundles)} bundles and {len(apps_store)} apps."
    )

    summary_sections = []
    final_bundle_repos = {
        bundle["repo"] for bundle in final_bundles if bundle.get("repo")
    }
    invalid_repos = [repo for repo in repos_data if repo not in final_bundle_repos]
    has_update_errors = bool(
        invalid_repos or errors["unavailable"] or errors["warnings"]
    )

    if has_update_errors:
        update_lines = []
        if invalid_repos:
            note_message = f"Note: {len(invalid_repos)}/{len(repos_data)} repos are invalid or excluded"
            print(f"[-] {note_message}")
            update_lines.append(f"## ⚠️ Update\n{note_message}:")
        else:
            update_lines.append("## ⚠️ Update:")

        for category_name, category_icon, category_errors in (
            ("Unavailable", "⛔", errors["unavailable"]),
            ("Warnings", "⚠️", errors["warnings"]),
        ):
            if category_errors:
                sorted_errors = sorted(category_errors)
                print(f"  {category_name} ({len(sorted_errors)}):")
                for error in sorted_errors:
                    print(f"    - {error}")
                update_lines.append(
                    f"### {category_icon} {category_name} ({len(sorted_errors)})\n"
                    + "\n".join(f"- {error}" for error in sorted_errors)
                )

        summary_sections.append("\n\n".join(update_lines))

    if incomplete_apps:
        sorted_incomplete_apps = sorted(incomplete_apps)
        print(
            f"[-] Note: {len(sorted_incomplete_apps)} apps have incomplete metadata (missing icon/name):"
        )
        for app_issue in sorted_incomplete_apps:
            print(f"  {app_issue}")
        summary_sections.append(
            f"### 📱 Incomplete Apps ({len(sorted_incomplete_apps)})\n"
            + "\n".join(sorted_incomplete_apps)
        )

    if summary_sections:
        append_step_summary("\n\n".join(summary_sections))
    return 0


if __name__ == "__main__":
    sys.exit(main())
