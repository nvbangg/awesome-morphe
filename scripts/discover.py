# Copyright (c) 2026 nvbangg (github.com/nvbangg)

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from common.utils import (
    BUNDLE_SOURCES_DIR,
    REPOS_JSON_PATH,
    ROOT_DIR,
    append_step_summary,
    build_repo_url,
    format_summary_section,
    load_json,
    parse_repo_url,
    save_json,
)
from discovery import (
    audit_readme,
    find_projects,
    jman,
    load_provider_sources,
    morphe_archive,
    official,
)

PROVIDERS = [
    "custom",
    "official",
    "morphe-archive",
    "jman",
]
PROVIDER_MODULES = [official, jman, morphe_archive]


def _run_providers() -> list[str]:
    warnings = []
    with ThreadPoolExecutor(max_workers=len(PROVIDER_MODULES)) as executor:
        futures = [executor.submit(module.discover) for module in PROVIDER_MODULES]
        for future in as_completed(futures):
            warning_message = future.result()
            if warning_message:
                warnings.append(warning_message)
    return warnings


def _load_provider_files() -> list[dict]:
    return [
        data
        for provider in PROVIDERS
        if (data := load_provider_sources(BUNDLE_SOURCES_DIR / f"{provider}.json"))
    ]


def _merge(provider_files: list[dict]) -> dict:
    canonical_keys = {}
    merged = {}
    for provider_dict in provider_files:
        for raw_key, data in sorted(provider_dict.items()):
            final_key = canonical_keys.setdefault(raw_key.lower(), raw_key)
            merged_data = merged.setdefault(final_key, {})
            for key, value in data.items():
                merged_data.setdefault(key, value)
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
        if not canonical_url:
            continue
        saved_url, metadata = existing_lower.get(
            canonical_url.lower(), (canonical_url, {})
        )
        synced[saved_url] = dict(metadata)
    return dict(sorted(synced.items(), key=lambda item: item[0].lower()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discover Morphe bundles and projects")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--daily", action="store_true", help="Also audit README links and find projects"
    )
    modes.add_argument(
        "--weekly",
        action="store_true",
        help="Also audit README links and find projects",
    )
    args = parser.parse_args(argv)

    warnings = _run_providers()
    print()
    provider_files = _load_provider_files()
    if not provider_files:
        message = "No usable provider files found; discovery stopped"
        print(message)
        warnings.append(message)

    summary_sections = ["## 🔎 Discovery:"]
    if warnings:
        summary_sections.append(
            format_summary_section(
                "Bundle sources",
                "\n".join(f"- {warning}" for warning in sorted(warnings)),
                len(warnings),
            )
        )

    if not provider_files:
        append_step_summary("\n\n".join(summary_sections))
        return 1

    merged = _merge(provider_files)
    print(f"Merged {len(merged)} unique sources")

    existing_repos = load_json(REPOS_JSON_PATH, {})
    synced_repos = _sync_repos(merged, existing_repos)
    print(f"Synced {len(synced_repos)} repos")
    save_json(REPOS_JSON_PATH, synced_repos)
    print(f"Saved to {REPOS_JSON_PATH.relative_to(ROOT_DIR)}")
    if args.daily or args.weekly:
        summary_sections.append(audit_readme.audit_repos_and_links())
        summary_sections.append(find_projects.run())
    if len(summary_sections) > 1:
        append_step_summary("\n\n".join(summary_sections))
    return 0


if __name__ == "__main__":
    sys.exit(main())
