# Copyright (c) 2026 nvbangg (github.com/nvbangg)

import re
import unicodedata
import urllib.parse
from datetime import UTC, datetime, timedelta

from utils import (
    BUNDLES_JSON_PATH,
    HISTORY_PATH,
    PACKAGE_EXAMPLE,
    PACKAGE_UNIVERSAL,
    WHATS_NEW_JSON_PATH,
    WHATS_NEW_PATH,
    append_step_summary,
    load_json,
    save_json,
    set_step_output,
)

WHATS_NEW_MAX_ENTRIES = 14
DISPLAY_ITEM_LIMIT = 3
EXISTING_APP_PATCH_LIMIT = 6
DEFAULT_BUNDLE_RANK = 9999
BASE_WEB_URL = "https://awesome-morphe.vercel.app"
WHATS_NEW_TAB = "#whats-new"


def is_valid_package_name(package_name: str) -> bool:
    return package_name == PACKAGE_UNIVERSAL or (
        "." in package_name
        and " " not in package_name
        and package_name != PACKAGE_EXAMPLE
    )


def format_app_name(package_name: str, app_metadata: dict) -> str:
    metadata = app_metadata.get(package_name)
    if isinstance(metadata, dict):
        return metadata.get("name") or package_name
    return metadata if isinstance(metadata, str) else package_name


def normalize_patch_name(name: str) -> str:
    text = unicodedata.normalize("NFKC", name).lower()
    text = re.sub(r"['\"\u2018\u2019\u201c\u201d`\u300c\u300d\u300e\u300f]", "", text)
    text = re.sub(
        r"[-_\u2010-\u2015:\(\)\[\]\{\}\u3010\u3011\u3008-\u300f,;!/|\\~?。、]",
        " ",
        text,
    )
    return " ".join(text.split())


def should_show_bundle_owner(display_name: str, owner: str) -> bool:
    if not owner:
        return False
    clean_name = re.sub(r"[^a-zA-Z]", "", display_name).lower()
    clean_owner = re.sub(r"[^a-zA-Z]", "", owner).lower()
    if not clean_owner or not clean_name:
        return display_name.lower() != owner.lower()
    return not (
        clean_name == clean_owner
        or clean_owner in clean_name
        or clean_name in clean_owner
    )


def make_url(
    bundle_source: str | None = None,
    bundle_repo: str | None = None,
    app: str | None = None,
    patch: str | None = None,
) -> str:
    parts = []
    if bundle_source and bundle_repo:
        parts.append(f"{bundle_source}={urllib.parse.quote(bundle_repo)}")
    if app:
        parts.append(f"app={urllib.parse.quote(app)}")
    if patch:
        parts.append(f"patch={urllib.parse.quote(patch)}")
    return f"{BASE_WEB_URL}/?{'&'.join(parts)}{WHATS_NEW_TAB}" if parts else ""


def bundle_sort_key(bundle: dict) -> tuple:
    hot_rank = bundle.get("hotRank")
    is_unofficial = 1 if hot_rank is None else 0
    rank_value = hot_rank if hot_rank is not None else 0
    stars = bundle.get("stars", 0) or 0
    updated_at = bundle.get("updatedAt", 0) or 0
    name = (bundle.get("name") or bundle.get("repo", "")).lower()
    repo = (bundle.get("repo") or "").lower()
    return (is_unofficial, rank_value, -stars, -updated_at, name, repo)


def get_app_sort_key(
    package_name: str,
    app_metadata: dict,
    patch_count: int = 0,
) -> tuple:
    is_universal = 1 if package_name == PACKAGE_UNIVERSAL else 0
    app_name = format_app_name(package_name, app_metadata)
    metadata = app_metadata.get(package_name)
    min_installs = metadata.get("minInstalls", 0) if isinstance(metadata, dict) else 0
    return (
        is_universal,
        -min_installs,
        -patch_count,
        app_name.lower(),
        package_name.lower(),
    )


def extract_bundle_metadata(
    bundles: list[dict],
) -> tuple[dict[str, str], dict[str, str], dict[str, int]]:
    bundle_names = {}
    bundle_sources = {}
    bundle_order = {}

    sorted_bundles = sorted(bundles, key=bundle_sort_key)
    for rank, bundle in enumerate(sorted_bundles):
        source = bundle.get("source", "github")
        repo = bundle.get("repo", "")
        if not repo:
            continue

        bundle_names[repo] = bundle.get("name") or repo.split("/")[-1]
        bundle_sources[repo] = source
        bundle_order[repo] = rank

    return bundle_names, bundle_sources, bundle_order


def build_new_bundles(bundles_json: dict) -> dict:
    compatibilities = bundles_json.get("compatibilities", [])
    new_bundles: dict[str, dict[str, list[str]]] = {}

    for bundle in bundles_json.get("bundles", []):
        repo = bundle.get("repo")
        patches = bundle.get("patches", [])
        if not repo or not patches:
            continue

        patches_dict: dict[str, set[str]] = {}
        for patch in patches:
            if not (patch_name := patch.get("name")):
                continue

            compat_key = patch.get("compatiblePackagesKey")
            if compat_key is not None and compat_key < len(compatibilities):
                has_valid_package = False
                for item in compatibilities[compat_key]:
                    if (
                        isinstance(item, dict)
                        and (package_name := item.get("packageName"))
                        and is_valid_package_name(package_name)
                    ):
                        patches_dict.setdefault(package_name, set()).add(patch_name)
                        has_valid_package = True
                if not has_valid_package:
                    patches_dict.setdefault(PACKAGE_UNIVERSAL, set()).add(patch_name)
            else:
                patches_dict.setdefault(PACKAGE_UNIVERSAL, set()).add(patch_name)

        if patches_dict:
            new_bundles[repo] = {
                package_name: sorted(patches_dict[package_name])
                for package_name in sorted(patches_dict)
            }
    return dict(sorted(new_bundles.items(), key=lambda item: item[0].lower()))


def count_app_patches(
    bundles_dict: dict[str, dict[str, list[str]]],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for bundle_apps in bundles_dict.values():
        for package_name, patches in bundle_apps.items():
            counts[package_name] = counts.get(package_name, 0) + len(patches)
    return counts


def build_json_diff(
    old_bundles: dict,
    new_bundles: dict,
    app_metadata: dict,
    bundle_order: dict[str, int],
    app_patch_counts: dict[str, int] | None = None,
) -> dict:
    app_patch_counts = app_patch_counts or {}
    json_diff = {}

    for repo, patches_dict in sorted(
        new_bundles.items(),
        key=lambda item: bundle_order.get(item[0], DEFAULT_BUNDLE_RANK),
    ):
        if repo not in old_bundles:
            apps = {
                package_name: {
                    "patches": sorted(patches_dict[package_name]),
                    "isNew": True,
                }
                for package_name in sorted(
                    patches_dict,
                    key=lambda package_name: get_app_sort_key(
                        package_name,
                        app_metadata,
                        app_patch_counts.get(
                            package_name, len(patches_dict[package_name])
                        ),
                    ),
                )
            }
            if apps:
                json_diff[repo] = {
                    "apps": apps,
                    "isNew": True,
                }
        else:
            old_patches_dict = old_bundles[repo]
            apps_dict = {}

            for package_name in sorted(
                patches_dict,
                key=lambda package_name: get_app_sort_key(
                    package_name,
                    app_metadata,
                    app_patch_counts.get(package_name, len(patches_dict[package_name])),
                ),
            ):
                if package_name not in old_patches_dict:
                    apps_dict[package_name] = {
                        "patches": sorted(patches_dict[package_name]),
                        "isNew": True,
                    }
                elif added_patches := set(patches_dict[package_name]) - set(
                    old_patches_dict.get(package_name, [])
                ):
                    apps_dict[package_name] = {"patches": sorted(added_patches)}

            if apps_dict:
                json_diff[repo] = {
                    "apps": apps_dict,
                }
    return json_diff


def render_patches(
    package_name: str,
    patches: list[str],
    limit: int = DISPLAY_ITEM_LIMIT,
) -> list[str]:
    sorted_patches = sorted(patches)
    total_patches = len(sorted_patches)
    lines = []
    display_count = total_patches if total_patches <= limit + 1 else limit

    for patch_name in sorted_patches[:display_count]:
        patch_url = make_url(app=package_name, patch=patch_name)
        lines.append(f"    + 🧩 [{patch_name}]({patch_url})")

    if total_patches > display_count:
        remaining_count = total_patches - display_count
        lines.append(f"    + _...and {remaining_count} more patches_")

    return lines


def render_apps(
    package_names: list[str],
    app_metadata: dict,
    limit: int = DISPLAY_ITEM_LIMIT,
) -> list[str]:
    lines = []
    total_apps = len(package_names)
    display_count = total_apps if total_apps <= limit + 1 else limit

    for package_name in package_names[:display_count]:
        app_name = format_app_name(package_name, app_metadata)
        app_url = make_url(app=package_name)
        lines.append(f"    + 📱 [{app_name}]({app_url})")

    if total_apps > display_count:
        remaining_count = total_apps - display_count
        lines.append(f"    + _...and {remaining_count} more apps_")

    return lines


def generate_markdown(
    json_diff: dict,
    old_history: dict,
    app_metadata: dict,
    bundle_names: dict,
    bundle_sources: dict,
    bundle_order: dict[str, int],
    app_patch_counts: dict[str, int] | None = None,
) -> str:
    app_patch_counts = app_patch_counts or {}
    known_apps = {
        package_name for bundle in old_history.values() for package_name in bundle
    }
    known_patches_by_app: dict[str, set[str]] = {}
    for bundle in old_history.values():
        for package_name, patches in bundle.items():
            known_patches_by_app.setdefault(package_name, set()).update(
                normalize_patch_name(patch_name) for patch_name in patches
            )

    new_bundle_repos = [
        repo for repo, data in json_diff.items() if data.get("isNew", False)
    ]
    new_bundle_repos.sort(key=lambda repo: bundle_order.get(repo, DEFAULT_BUNDLE_RANK))

    new_apps_map: dict[str, dict[str, str]] = {}
    existing_apps_new_patches_map: dict[str, dict[str, str]] = {}
    bundle_added_apps_map: dict[str, list[str]] = {}

    for repo, bundle_data in json_diff.items():
        is_new_bundle = bundle_data.get("isNew", False)
        apps_data = bundle_data.get("apps", {})
        for package_name, app_data in apps_data.items():
            patches = app_data.get("patches", [])
            is_new_app_in_bundle = app_data.get("isNew", False)

            if (
                not is_new_bundle
                and is_new_app_in_bundle
                and package_name in known_apps
                and package_name != PACKAGE_UNIVERSAL
                and package_name != PACKAGE_EXAMPLE
            ):
                bundle_added_apps_map.setdefault(repo, []).append(package_name)
                continue

            if not patches:
                continue

            if package_name not in known_apps:
                target_map = new_apps_map.setdefault(package_name, {})
                for patch_name in patches:
                    target_map.setdefault(normalize_patch_name(patch_name), patch_name)
            else:
                known_set = known_patches_by_app.get(package_name, set())
                for patch_name in patches:
                    if normalize_patch_name(patch_name) not in known_set:
                        target_map = existing_apps_new_patches_map.setdefault(
                            package_name, {}
                        )
                        target_map.setdefault(
                            normalize_patch_name(patch_name), patch_name
                        )

    if (
        not new_bundle_repos
        and not new_apps_map
        and not existing_apps_new_patches_map
        and not bundle_added_apps_map
    ):
        return ""

    markdown_sections = [f"✨ [_View full changelog_]({BASE_WEB_URL}/{WHATS_NEW_TAB})"]

    if new_bundle_repos:
        bundle_lines = []
        for repo in new_bundle_repos:
            display_name = bundle_names.get(repo) or repo.split("/")[-1]
            source = bundle_sources.get(repo, "github")
            owner = repo.split("/")[0] if "/" in repo else ""
            owner_suffix = (
                f" (by {owner})"
                if should_show_bundle_owner(display_name, owner)
                else ""
            )
            bundle_url = make_url(bundle_source=source, bundle_repo=repo)
            bundle_lines.append(
                f"+ 📦 (✨New) [{display_name}]({bundle_url}){owner_suffix}"
            )
        markdown_sections.append("\n".join(bundle_lines))

    if new_apps_map:
        app_lines = []
        for package_name in sorted(
            new_apps_map.keys(),
            key=lambda package_name: get_app_sort_key(
                package_name,
                app_metadata,
                app_patch_counts.get(package_name, len(new_apps_map[package_name])),
            ),
        ):
            app_name = format_app_name(package_name, app_metadata)
            app_url = make_url(app=package_name)
            app_lines.append(f"+ 📱 (✨New) [{app_name}]({app_url})")
            patch_list = list(new_apps_map[package_name].values())
            app_lines.extend(render_patches(package_name, patch_list))
        markdown_sections.append("\n".join(app_lines))

    if existing_apps_new_patches_map:
        app_lines = []
        for package_name in sorted(
            existing_apps_new_patches_map.keys(),
            key=lambda package_name: get_app_sort_key(
                package_name,
                app_metadata,
                app_patch_counts.get(
                    package_name, len(existing_apps_new_patches_map[package_name])
                ),
            ),
        ):
            app_name = format_app_name(package_name, app_metadata)
            app_lines.append(f"- 📱 {app_name}")
            patch_list = list(existing_apps_new_patches_map[package_name].values())
            app_lines.extend(
                render_patches(
                    package_name,
                    patch_list,
                    limit=EXISTING_APP_PATCH_LIMIT,
                )
            )
        markdown_sections.append("\n".join(app_lines))

    if bundle_added_apps_map:
        bundle_addition_lines = []
        for repo in sorted(
            bundle_added_apps_map.keys(),
            key=lambda item_repo: bundle_order.get(item_repo, DEFAULT_BUNDLE_RANK),
        ):
            package_names = sorted(
                bundle_added_apps_map[repo],
                key=lambda package_name: get_app_sort_key(
                    package_name,
                    app_metadata,
                    app_patch_counts.get(
                        package_name,
                        len(
                            json_diff.get(repo, {})
                            .get("apps", {})
                            .get(package_name, {})
                            .get("patches", [])
                        ),
                    ),
                ),
            )

            if not package_names:
                continue

            display_name = bundle_names.get(repo) or repo.split("/")[-1]
            source = bundle_sources.get(repo, "github")
            owner = repo.split("/")[0] if "/" in repo else ""
            owner_suffix = (
                f" (by {owner})"
                if should_show_bundle_owner(display_name, owner)
                else ""
            )
            bundle_url = make_url(bundle_source=source, bundle_repo=repo)
            current_bundle_lines = [
                f"- 📦 [{display_name}]({bundle_url}){owner_suffix}"
            ]
            current_bundle_lines.extend(render_apps(package_names, app_metadata))
            bundle_addition_lines.append("\n".join(current_bundle_lines))

        if bundle_addition_lines:
            markdown_sections.append("\n\n".join(bundle_addition_lines))

    return "\n\n".join(markdown_sections)


def main() -> None:
    old_history = load_json(HISTORY_PATH, {})
    whats_new_data = load_json(WHATS_NEW_JSON_PATH, [])
    bundles_json = load_json(BUNDLES_JSON_PATH, {})
    app_metadata = bundles_json.get("store", {})
    bundle_names, bundle_sources, bundle_order = extract_bundle_metadata(
        bundles_json.get("bundles", [])
    )

    current_time = datetime.now(UTC) + timedelta(hours=1)
    today_str = current_time.strftime(f"%B {current_time.day}, %Y")

    new_bundles = build_new_bundles(bundles_json)
    app_patch_counts = count_app_patches(new_bundles)
    json_diff = build_json_diff(
        old_history,
        new_bundles,
        app_metadata,
        bundle_order,
        app_patch_counts,
    )

    if not json_diff:
        info_message = (
            "No changes detected in patch bundles. Skipping What's New generation."
        )
        print(f"[-] {info_message}")
        append_step_summary(f"### ⚠️ What's new\n- {info_message}")
        set_step_output("success", "true")
        return

    latest_entry = (
        whats_new_data[0]
        if whats_new_data and isinstance(whats_new_data[0], dict)
        else {}
    )
    if latest_entry.get("date") == today_str:
        warning_message = (
            f"Date '{today_str}' already exists in"
            f" `{WHATS_NEW_JSON_PATH.name}`. Skipping What's New generation."
        )
        print(f"[-] {warning_message}")
        append_step_summary(f"### ⚠️ What's new\n- {warning_message}")
        return

    if markdown_str := generate_markdown(
        json_diff,
        old_history,
        app_metadata,
        bundle_names,
        bundle_sources,
        bundle_order,
        app_patch_counts,
    ):
        WHATS_NEW_PATH.parent.mkdir(parents=True, exist_ok=True)
        WHATS_NEW_PATH.write_text(markdown_str + "\n", encoding="utf-8")
        print(f"Generated {WHATS_NEW_PATH.name}")
    else:
        info_message = (
            "No new patches or apps to announce. Skipped"
            f" `{WHATS_NEW_PATH.name}` generation."
        )
        print(f"[-] {info_message}")
        append_step_summary(f"### ⚠️ What's new\n- {info_message}")

    whats_new_data.insert(0, {"date": today_str, "bundles": json_diff})
    save_json(WHATS_NEW_JSON_PATH, whats_new_data[:WHATS_NEW_MAX_ENTRIES])
    print(f"Updated {WHATS_NEW_JSON_PATH.name}")

    save_json(HISTORY_PATH, new_bundles)
    print(f"Saved baseline to {HISTORY_PATH.name}")
    set_step_output("success", "true")


if __name__ == "__main__":
    main()
