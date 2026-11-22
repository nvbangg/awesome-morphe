# Copyright (c) 2026 nvbangg (github.com/nvbangg)

from concurrent.futures import ThreadPoolExecutor, as_completed

from common.constants import (
    CUSTOM_JSON_PATH,
    DISCOVERY_JSON_PATH,
    ROOT_DIR,
)
from common.files import load_json, save_json
from common.models import DISCOVERY, SOURCES
from common.repositories import build_repo_url, parse_repo_url
from common.summary import append_step_summary, format_summary_section
from discovery import (
    jman,
    morphe_archive,
    official,
)

PROVIDER_MODULES = {"official": official, "morphe-archive": morphe_archive, "jman": jman}


def _run_providers(providers: dict[str, list[str]]) -> list[str]:
    warnings = []
    with ThreadPoolExecutor(max_workers=len(PROVIDER_MODULES)) as executor:
        futures = {executor.submit(module.discover): name for name, module in PROVIDER_MODULES.items()}
        for future in as_completed(futures):
            name = futures[future]
            discovered, error = future.result()
            if discovered:
                providers[name] = sorted(set(discovered))
                print(f"[{name}] Discovered {len(providers[name])} sources")
            else:
                saved = "kept saved sources" if providers.get(name) else "no saved sources available"
                warning_message = f"[{name}]: {error or 'No sources found'}; {saved}"
                print(f"[-] {warning_message}")
                warnings.append(warning_message)
    return warnings


def run() -> int:
    registry = DISCOVERY.validate_python(load_json(DISCOVERY_JSON_PATH, {"providers": {}, "repositories": {}}))
    custom = SOURCES.validate_python(load_json(CUSTOM_JSON_PATH))
    warnings = _run_providers(registry["providers"])
    print()
    repositories = {}
    for urls in registry["providers"].values():
        for url in urls:
            source, repo = parse_repo_url(url)
            if canonical_url := build_repo_url(source, repo):
                repositories.setdefault(canonical_url.lower(), {})
    for url, config in custom.items():
        source, repo = parse_repo_url(url)
        if canonical_url := build_repo_url(source, repo):
            repositories.pop(canonical_url.lower(), None)
            config = {
                field: value
                for field, value in config.items()
                if field == "revancedStars" or (field == "enabled" and value is False)
            }
            repositories[canonical_url.lower()] = config
    if not repositories:
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
                display="details-open",
            )
        )

    if not repositories:
        append_step_summary("\n\n".join(summary_sections))
        return 1

    for url, config in repositories.items():
        if repo_id := registry["repositories"].get(url, {}).get("id"):
            config["id"] = repo_id
    save_json(DISCOVERY_JSON_PATH, DISCOVERY.validate_python({**registry, "repositories": repositories}))
    print(f"Synced {len(repositories)} repos")
    print(f"Saved to {DISCOVERY_JSON_PATH.relative_to(ROOT_DIR)}")
    if len(summary_sections) > 1:
        append_step_summary("\n\n".join(summary_sections))
    return 0
