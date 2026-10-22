# Copyright (c) 2026 nvbangg (github.com/nvbangg)

import hashlib
import json
import re
import time
from typing import Any

from common.utils import (
    BUNDLES_DIR,
    DEFAULT_BRANCHES,
    PACKAGE_EXAMPLE,
    PACKAGE_UNIVERSAL,
    PATCHES_DIR,
    load_json,
    parse_repo_url,
    parse_timestamp,
)

_BUNDLE_NAME_SUFFIX_RE = re.compile(
    r"(?i)(?: for use with morphe| for morphe|['\u2019]s morphe patches|['\u2019]s patches| morphe| patches| patch)+$"
)


def compute_app_hash(raw_patches: list[dict]) -> str:
    sorted_patches = sorted(raw_patches, key=lambda patch: patch.get("name", ""))
    content = json.dumps(sorted_patches, sort_keys=True, ensure_ascii=False).encode(
        "utf-8"
    )
    return hashlib.md5(content).hexdigest()[:16]


def parse_version_item(item: Any) -> dict | None:
    if isinstance(item, str):
        return {"version": item}
    if isinstance(item, dict) and "version" in item:
        entry = {"version": item["version"]}
        if item.get("isExperimental") or item.get("experimental"):
            entry["isExperimental"] = True
        return entry
    return None


def strip_patch(patch: dict, discovered_names: dict[str, str]) -> dict | None:
    if not isinstance(patch, dict) or not (name := patch.get("name")):
        return None

    output: dict = {"name": name}
    if desc := patch.get("description"):
        output["description"] = desc
    if patch.get("isPreRelease"):
        output["isPreRelease"] = True
    default_val = patch.get("default", patch.get("use", True))
    if default_val is False:
        output["default"] = False

    if options := patch.get("options"):
        options_list = []
        for opt in options:
            if isinstance(opt, dict) and "key" in opt:
                opt_entry = {"key": opt["key"]}
                if opt.get("title"):
                    opt_entry["title"] = opt["title"]
                if opt.get("description"):
                    opt_entry["description"] = opt["description"]
                options_list.append(opt_entry)
        if options_list:
            output["options"] = options_list

    compatible_packages = patch.get("compatiblePackages")
    package_entries = (
        [
            (package_name, versions, None)
            for package_name, versions in compatible_packages.items()
        ]
        if isinstance(compatible_packages, dict)
        else [
            (
                entry.get("packageName"),
                entry.get("targets", []),
                entry.get("name"),
            )
            for entry in compatible_packages
            if isinstance(entry, dict) and entry.get("packageName")
        ]
        if isinstance(compatible_packages, list)
        else []
    )

    compatibility_targets = []
    for package_name, versions, app_name in package_entries:
        if app_name:
            discovered_names[package_name] = app_name
        targets = [
            parsed
            for version_item in (versions or [])
            if (parsed := parse_version_item(version_item))
        ]
        target_entry = {"packageName": package_name}
        if targets:
            target_entry["targets"] = targets
        compatibility_targets.append(target_entry)

    if compatibility_targets:
        output["compatiblePackages"] = compatibility_targets
    return output


def parse_patches_list(
    raw_patches_data: Any,
    discovered_names: dict[str, str],
    is_dev_branch: bool = False,
    main_patch_names: set[str] | None = None,
) -> tuple[list[dict] | None, str | None]:
    if not isinstance(raw_patches_data, dict):
        return None, "Invalid data"

    raw_list = raw_patches_data.get("patches")
    if not isinstance(raw_list, list):
        return None, "Invalid data"
    if len(raw_list) == 0:
        return None, "No patches found"

    valid_patches = []
    bundle_apps = set()
    for patch in raw_list:
        if not isinstance(patch, dict):
            continue
        name = patch.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        if is_dev_branch and main_patch_names and name not in main_patch_names:
            patch["isPreRelease"] = True
        if not (patch_dict := strip_patch(patch, discovered_names)):
            continue
        compat_packages = patch_dict.get("compatiblePackages")
        if compat_packages:
            for item in compat_packages:
                if package_name := item.get("packageName"):
                    bundle_apps.add(package_name)
        else:
            bundle_apps.add(PACKAGE_UNIVERSAL)
        valid_patches.append(patch_dict)

    if not valid_patches:
        return None, "Invalid data"
    if bundle_apps == {PACKAGE_EXAMPLE}:
        return None, "Only contains `com.example.app`"

    return valid_patches, None


def load_branch_data(
    file_prefix: str,
    branch: str,
    has_sha: bool,
    discovered_names: dict[str, str],
    is_dev_branch: bool = False,
    main_patch_names: set[str] | None = None,
) -> tuple[dict | None, list[dict] | None, list[dict] | None, str | None]:
    if not has_sha:
        return None, None, None, None
    bundle_file = BUNDLES_DIR / f"{file_prefix}~{branch}.json"
    list_file = PATCHES_DIR / f"{file_prefix}~{branch}.json"
    if not bundle_file.exists():
        return None, None, None, None
    bundle = load_json(bundle_file)
    download_url = bundle.get("download_url") if isinstance(bundle, dict) else None
    if not isinstance(download_url, str) or not download_url:
        return None, None, None, None
    if not list_file.exists():
        return None, None, None, "Missing `patches-list.json`"
    try:
        raw = load_json(list_file)
        patches, reason = parse_patches_list(
            raw,
            discovered_names,
            is_dev_branch=is_dev_branch,
            main_patch_names=main_patch_names,
        )
    except (AttributeError, TypeError, ValueError):
        return None, None, None, "Invalid data"
    if not patches:
        return None, None, None, reason
    return bundle, patches, raw["patches"], None


def process(
    bundle_sources: dict,
    apps_dict: dict,
    repos_data: dict,
    existing_hashes: dict,
    errors: list[str] | None = None,
    existing_bundles: dict | None = None,
) -> dict[str, dict[str, str]]:
    keys_to_remove = []
    now_ms = int(time.time() * 1000)
    all_new_hashes: dict[str, dict[str, str]] = {}

    print(f"\nParsing local patches and bundles for {len(bundle_sources)} sources...")
    for repo_url, source_entry in bundle_sources.items():
        source, repo = parse_repo_url(repo_url)
        if not source or not repo:
            continue
        owner = repo.split("/", 1)[0]
        repo_metadata = repos_data[repo_url]
        main_sha = repo_metadata.get("main")
        dev_sha = repo_metadata.get("dev")
        if not main_sha and not dev_sha:
            keys_to_remove.append(repo_url)
            continue
        file_prefix = f"{source}~{repo.replace('/', '~')}"
        main_names = {}
        dev_names = {}
        main_bundle, main_patches, main_raw, main_reason = load_branch_data(
            file_prefix,
            "main",
            bool(main_sha),
            main_names,
        )
        main_patch_names = {patch["name"] for patch in main_patches or []}
        dev_bundle, dev_patches, dev_raw, dev_reason = load_branch_data(
            file_prefix,
            "dev",
            bool(dev_sha),
            dev_names,
            is_dev_branch=True,
            main_patch_names=main_patch_names,
        )
        branch_errors = [
            (branch, reason)
            for branch, reason in (("main", main_reason), ("dev", dev_reason))
            if reason
        ]
        if not (main_patches or dev_patches):
            keys_to_remove.append(repo_url)
            if errors is not None and branch_errors:
                reason = (
                    main_reason
                    if main_reason and main_reason == dev_reason
                    else "; ".join(
                        f"({branch}) {reason}" for branch, reason in branch_errors
                    )
                )
                errors.append(f"{repo_url}: {reason}")
            continue
        main_timestamp = (
            parse_timestamp(main_bundle.get("created_at")) if main_bundle else 0
        )
        dev_timestamp = (
            parse_timestamp(dev_bundle.get("created_at")) if dev_bundle else 0
        )
        use_dev = bool(
            dev_patches and (not main_patches or dev_timestamp > main_timestamp)
        )
        source_entry["source"] = source
        source_entry["isPreRelease"] = not bool(main_patches)
        source_entry["updatedAt"] = dev_timestamp if use_dev else main_timestamp
        chosen_patches = (dev_patches if use_dev else main_patches) or []
        chosen_raw_patches = dev_raw if use_dev else main_raw
        discovered_names = dev_names if use_dev else main_names

        raw_name = repo_metadata.get("name") or ""
        if raw_name:
            raw_name = (
                ""
                if raw_name.lower() == "morphe patches"
                else _BUNDLE_NAME_SUFFIX_RE.sub("", raw_name).strip("- ")
            )
        source_entry["name"] = raw_name or owner

        raw_app_patches_map: dict[str, list[dict]] = {}
        for raw_patch in chosen_raw_patches or []:
            if not isinstance(raw_patch, dict):
                continue
            compat = raw_patch.get("compatiblePackages")
            packages = (
                list(compat.keys())
                if isinstance(compat, dict)
                else [
                    item.get("packageName")
                    for item in compat
                    if isinstance(item, dict) and item.get("packageName")
                ]
                if isinstance(compat, list)
                else []
            ) or [PACKAGE_UNIVERSAL]
            for package_name in packages:
                raw_app_patches_map.setdefault(package_name, []).append(raw_patch)

        app_first_seen_map = (
            source_entry.get("appFirstSeen")
            if isinstance(source_entry.get("appFirstSeen"), dict)
            else {}
        )
        current_apps_in_bundle: set[str] = set()

        existing_bundle = (existing_bundles or {}).get(repo_url, {})
        existing_patches = {
            patch["name"]: patch
            for patch in existing_bundle.get("patches", [])
            if isinstance(patch, dict) and patch.get("name")
        }
        bundle_first_seen = existing_bundle.get("firstSeen", now_ms)

        final_patches = []
        for patch in chosen_patches:
            compatible_packages = patch.pop("compatiblePackages", None)
            if compatible_packages:
                for compatible_package in compatible_packages:
                    package_name = compatible_package.get("packageName")
                    if package_name and package_name != PACKAGE_UNIVERSAL:
                        current_apps_in_bundle.add(package_name)
                        apps_dict.setdefault(package_name, {})
                        if (
                            app_name := discovered_names.get(package_name)
                        ) and not apps_dict[package_name].get("name"):
                            apps_dict[package_name]["name"] = app_name
                        if package_name not in app_first_seen_map:
                            app_first_seen_map[package_name] = now_ms
            else:
                current_apps_in_bundle.add(PACKAGE_UNIVERSAL)

            patch_name = patch["name"]
            patch_first_seen = (
                existing_patches[patch_name].get("firstSeen", bundle_first_seen)
                if patch_name in existing_patches
                else now_ms
            )

            ordered_patch = {"name": patch_name}
            if desc := patch.get("description"):
                ordered_patch["description"] = desc
            ordered_patch["firstSeen"] = patch_first_seen
            if patch.get("isPreRelease"):
                ordered_patch["isPreRelease"] = True
            if patch.get("default") is False:
                ordered_patch["default"] = False
            if options := patch.get("options"):
                ordered_patch["options"] = options
            if compatible_packages:
                ordered_patch["compatiblePackages"] = compatible_packages
            final_patches.append(ordered_patch)

        if (
            PACKAGE_UNIVERSAL in current_apps_in_bundle
            and PACKAGE_UNIVERSAL not in app_first_seen_map
        ):
            app_first_seen_map[PACKAGE_UNIVERSAL] = now_ms

        sorted_apps = sorted(current_apps_in_bundle)
        source_entry["patches"] = final_patches
        source_entry["appFirstSeen"] = {
            package_name: app_first_seen_map[package_name]
            for package_name in sorted_apps
            if package_name in app_first_seen_map
        }

        bundle_timestamp = source_entry.get("updatedAt", 0)
        repo_hashes = existing_hashes.get(repo_url, {})
        new_repo_hashes = {}
        app_updates_map = (
            dict(source_entry.get("appUpdates"))
            if isinstance(source_entry.get("appUpdates"), dict)
            else {}
        )

        for package_name in source_entry["appFirstSeen"]:
            raw_app_patches = raw_app_patches_map.get(package_name, [])
            cur_hash = compute_app_hash(raw_app_patches)
            new_repo_hashes[package_name] = cur_hash
            prev_hash = repo_hashes.get(package_name)

            if prev_hash is None:
                app_updates_map.setdefault(package_name, bundle_timestamp)
            elif prev_hash != cur_hash:
                app_updates_map[package_name] = bundle_timestamp

        source_entry["appUpdates"] = {
            package_name: app_updates_map[package_name]
            for package_name in source_entry["appFirstSeen"]
            if package_name in app_updates_map
        }
        all_new_hashes[repo_url] = new_repo_hashes

    for key in keys_to_remove:
        bundle_sources.pop(key, None)

    return all_new_hashes


def cleanup_orphan_files(repos_data: dict) -> None:
    target_files = {
        f"{source}~{repo.replace('/', '~')}~{branch}.json"
        for repo_url in repos_data
        for source, repo in [parse_repo_url(repo_url)]
        if source and repo
        for branch in DEFAULT_BRANCHES
    }
    for directory in (BUNDLES_DIR, PATCHES_DIR):
        if directory.exists():
            for filepath in directory.glob("*.json"):
                if filepath.name not in target_files:
                    filepath.unlink()
