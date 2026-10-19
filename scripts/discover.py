# Copyright (c) 2026 nvbangg (github.com/nvbangg)

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from providers import jman, load_provider_sources, morphe_archive, official
from utils import (
    DISCOVER_DIR,
    REPOS_JSON_PATH,
    ROOT_DIR,
    append_step_summary,
    build_repo_url,
    load_json,
    parse_repo_url,
    save_json,
)

PROVIDERS = [
    "custom",
    "official",
    "morphe-archive",
    "jman",
]
PROVIDER_MODULES = [official, jman, morphe_archive]
PROVIDER_PRIORITY = {f"{name}.json": index for index, name in enumerate(PROVIDERS)}


def _run_providers() -> list[str]:
    warnings = []
    with ThreadPoolExecutor(max_workers=len(PROVIDER_MODULES)) as executor:
        futures = [executor.submit(module.discover) for module in PROVIDER_MODULES]
        for future in as_completed(futures):
            warning_message = future.result()
            if warning_message:
                warnings.append(warning_message)
    return warnings


def _load_provider_files() -> list[tuple[str, dict]]:
    return [
        (f"{provider}.json", data)
        for provider in PROVIDERS
        if (data := load_provider_sources(DISCOVER_DIR / f"{provider}.json"))
    ]


def _merge(provider_files: list[tuple[str, dict]]) -> dict:
    groups = {}
    for filename, provider_dict in provider_files:
        priority = PROVIDER_PRIORITY.get(filename, 99)
        for raw_key, data in provider_dict.items():
            groups.setdefault(raw_key.lower(), []).append((priority, raw_key, data))

    merged = {}
    for entries in groups.values():
        entries.sort(key=lambda entry: (entry[0], entry[1]))
        final_key = entries[0][1]
        merged_data = {}
        for _, _, data in entries:
            for key, value in data.items():
                if key not in merged_data:
                    merged_data[key] = value
        merged[final_key] = merged_data
    return merged


def _sync_repos(merged: dict, existing_repos: dict) -> dict:
    existing_lower = {
        existing_repo.lower(): (existing_repo, existing_metadata)
        for existing_repo, existing_metadata in existing_repos.items()
        if isinstance(existing_metadata, dict)
    }
    synced = {}
    for repo_url, entry in merged.items():
        if entry.get("enabled") is False:
            continue
        source, repo = parse_repo_url(repo_url)
        if not source or not repo:
            continue
        canonical_url = build_repo_url(source, repo)
        saved_url, metadata = existing_lower.get(
            canonical_url.lower(), (canonical_url, {})
        )
        synced[saved_url] = dict(metadata)
    return dict(sorted(synced.items(), key=lambda item: item[0].lower()))


def main() -> int:
    warnings = _run_providers()
    print()
    provider_files = _load_provider_files()
    if not provider_files:
        message = "No usable provider files found; discovery stopped"
        print(message)
        warnings.append(message)

    if warnings:
        markdown_lines = [
            "## 🔎 Discover:\n",
            *[f"- {warning}" for warning in sorted(warnings)],
        ]
        append_step_summary("\n".join(markdown_lines))

    if not provider_files:
        return 1

    merged = _merge(provider_files)
    print(f"Merged {len(merged)} unique sources")

    existing_repos = load_json(REPOS_JSON_PATH, {})
    synced_repos = _sync_repos(merged, existing_repos)
    print(f"Synced {len(synced_repos)} repos")
    save_json(REPOS_JSON_PATH, synced_repos)
    print(f"Saved to {REPOS_JSON_PATH.relative_to(ROOT_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
