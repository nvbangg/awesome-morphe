# Copyright (c) 2026 nvbangg (github.com/nvbangg)

import hashlib
import json
import re
import time
from typing import Any

from utils import (
    BUNDLES_DIR,
    DEFAULT_BRANCHES,
    HASHES_PATH,
    HISTORY_PATH,
    PACKAGE_EXAMPLE,
    PACKAGE_UNIVERSAL,
    PATCHES_DIR,
    REPOS_JSON_PATH,
    build_repo_url,
    load_json,
    parse_repo_url,
    parse_timestamp,
    save_json,
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
        return None, "Invalid `patches-list.json`"

    raw_list = raw_patches_data.get("patches")
    if not isinstance(raw_list, list):
        return None, "Invalid `patches-list.json`"
    if len(raw_list) == 0:
        return None, "Empty `patches-list.json`"

    valid_patches = []
    bundle_apps = set()
    for patch in raw_list:
        if not isinstance(patch, dict) or not (name := patch.get("name")):
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
        return None, "Invalid `patches-list.json`"
    if bundle_apps == {PACKAGE_EXAMPLE}:
        return None, "Only contains `com.example.app`"

    return valid_patches, None


def load_branch_data(
    source: str,
    file_prefix: str,
    branch: str,
    has_sha: bool,
    discovered_names: dict[str, str],
    is_dev_branch: bool = False,
    main_patch_names: set[str] | None = None,
) -> tuple[dict | None, list[dict] | None, list[dict] | None, str | None]:
    if not has_sha:
        return None, None, None, "Missing `patches-bundle.json`"
    bundle_file = BUNDLES_DIR / f"{file_prefix}~{branch}.json"
    list_file = PATCHES_DIR / f"{file_prefix}~{branch}.json"
    if not bundle_file.exists():
        return None, None, None, "Missing `patches-bundle.json`"
    bundle = load_json(bundle_file)
    download_url = bundle.get("download_url") if isinstance(bundle, dict) else None
    mpp_source, mpp_repo = (
        parse_repo_url(download_url)
        if isinstance(download_url, str) and download_url.lower().endswith(".mpp")
        else (None, None)
    )
    if (
        mpp_source != source
        or mpp_repo.lower() != file_prefix.replace("~", "/").lower()
    ):
        return None, None, None, "Invalid `download_url`"
    if not list_file.exists():
        return None, None, None, "Missing `patches-list.json`"
    raw = load_json(list_file)
    patches, reason = parse_patches_list(
        raw,
        discovered_names,
        is_dev_branch=is_dev_branch,
        main_patch_names=main_patch_names,
    )
    if not patches:
        return None, None, None, reason
    return bundle, patches, raw["patches"], None


def process(
    bundle_sources: dict,
    apps_dict: dict,
    errors: dict[str, list[str]] | None = None,
    existing_bundles: dict | None = None,
) -> list:
    compatibilities_list = []
    compatibilities_map = {}

    def get_compatibility_key(compatibility_data: list) -> int:
        compatibility_json = json.dumps(compatibility_data, sort_keys=True)
        if compatibility_json in compatibilities_map:
            return compatibilities_map[compatibility_json]
        index = len(compatibilities_list)
        compatibilities_list.append(compatibility_data)
        compatibilities_map[compatibility_json] = index
        return index

    repos_data = load_json(REPOS_JSON_PATH, {})
    valid_target_files = {
        f"{repo.replace('/', '~')}~{branch}.json"
        for repo, repo_metadata in repos_data.items()
        if isinstance(repo_metadata, dict)
        for source in ("github", "gitlab")
        if isinstance(repo_metadata.get(source), dict)
        for branch in DEFAULT_BRANCHES
    }
    for directory in (BUNDLES_DIR, PATCHES_DIR):
        if directory.exists():
            for filepath in directory.glob("*.json"):
                if filepath.name not in valid_target_files:
                    filepath.unlink(missing_ok=True)

    keys_to_remove = []
    valid_apps_from_bundles = set()
    now_ms = int(time.time() * 1000)
    existing_hashes = load_json(HASHES_PATH, {})
    all_new_hashes: dict[str, dict[str, str]] = {}

    print(f"\nParsing local patches and bundles for {len(bundle_sources)} sources...")
    for repo, source_entry in bundle_sources.items():
        if not repo or "/" not in repo:
            continue
        owner, repo_name = repo.split("/", 1)
        file_prefix = f"{owner}~{repo_name}"
        repo_metadata = repos_data.get(repo, {})
        chosen_source = None
        main_bundle = None
        main_patches = None
        main_raw = None
        dev_bundle = None
        dev_patches = None
        dev_raw = None
        discovered_names = {}
        has_sha = False
        fail_reason = None

        for source in ("github", "gitlab"):
            source_metadata = repo_metadata.get(source)
            if not isinstance(source_metadata, dict):
                continue
            main_sha = source_metadata.get("main")
            dev_sha = source_metadata.get("dev")
            if not main_sha and not dev_sha:
                fail_reason = "Missing `patches-bundle.json`"
                continue
            has_sha = True

            cur_discovered_names = {}
            cur_main_bundle, cur_main_patches, cur_main_raw, main_reason = (
                load_branch_data(
                    source, file_prefix, "main", bool(main_sha), cur_discovered_names
                )
            )
            main_patch_names = (
                {patch["name"] for patch in cur_main_patches if "name" in patch}
                if cur_main_patches
                else set()
            )
            cur_dev_bundle, cur_dev_patches, cur_dev_raw, dev_reason = load_branch_data(
                source,
                file_prefix,
                "dev",
                bool(dev_sha),
                cur_discovered_names,
                is_dev_branch=True,
                main_patch_names=main_patch_names,
            )

            if cur_main_patches or cur_dev_patches:
                chosen_source = source
                main_bundle = cur_main_bundle
                main_patches = cur_main_patches
                main_raw = cur_main_raw
                dev_bundle = cur_dev_bundle
                dev_patches = cur_dev_patches
                dev_raw = cur_dev_raw
                discovered_names = cur_discovered_names
                break

            fail_reason = main_reason or dev_reason

        if not chosen_source:
            keys_to_remove.append(repo)
            message = fail_reason or (
                "Missing `patches-list.json`"
                if has_sha
                else "Missing `patches-bundle.json`"
            )
            print(f"[-] Excluding {repo}: {message}")
            if errors is not None:
                for source in ("github", "gitlab"):
                    if source in repo_metadata:
                        repo_url = build_repo_url(source, repo)
                        errors["unavailable"].append(f"{repo_url}: {message}")
            continue

        source_entry["source"] = chosen_source

        main_timestamp = (
            parse_timestamp(main_bundle.get("created_at"))
            if main_patches and main_bundle
            else 0
        )
        dev_timestamp = (
            parse_timestamp(dev_bundle.get("created_at"))
            if dev_patches and dev_bundle
            else 0
        )
        is_latest_dev = bool(
            dev_patches and (not main_patches or dev_timestamp > main_timestamp)
        )

        source_entry["isPreRelease"] = not bool(main_patches)
        source_entry["updatedAt"] = dev_timestamp if is_latest_dev else main_timestamp

        raw_name = repo_metadata.get("name") or ""
        if raw_name:
            raw_name = (
                ""
                if raw_name.lower() == "morphe patches"
                else _BUNDLE_NAME_SUFFIX_RE.sub("", raw_name).strip("- ")
            )
        source_entry["name"] = raw_name or owner

        chosen_patches = dev_patches if is_latest_dev else main_patches
        chosen_raw_patches = dev_raw if is_latest_dev else main_raw
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

        existing_bundle = (existing_bundles or {}).get(repo, {})
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
                        valid_apps_from_bundles.add(package_name)
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
                ordered_patch["compatiblePackagesKey"] = get_compatibility_key(
                    compatible_packages
                )
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
        repo_hashes = existing_hashes.get(repo, {})
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
        all_new_hashes[repo] = new_repo_hashes

    for key in keys_to_remove:
        bundle_sources.pop(key, None)

    apps_to_remove = [
        package_name
        for package_name in list(apps_dict.keys())
        if package_name not in valid_apps_from_bundles
        and package_name != PACKAGE_UNIVERSAL
    ]
    for package_name in apps_to_remove:
        del apps_dict[package_name]
        print(f"[-] Removed app '{package_name}' (no longer supported by any bundle)")

    valid_repos = set(bundle_sources.keys())
    cleaned_hashes = {
        repo: all_new_hashes[repo]
        for repo in sorted(valid_repos, key=str.lower)
        if repo in all_new_hashes
    }
    save_json(HASHES_PATH, cleaned_hashes)

    history_data = load_json(HISTORY_PATH, {})
    if history_data:
        cleaned_history = {
            repo: history_data[repo]
            for repo in sorted(history_data.keys(), key=str.lower)
            if repo in valid_repos
        }
        if cleaned_history != history_data:
            save_json(HISTORY_PATH, cleaned_history)

    return compatibilities_list
