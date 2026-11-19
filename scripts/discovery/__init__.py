from common.repositories import record_repo_rename, resolve_repo_url


def merge_sources(provider_data: list[dict], renames: dict[str, str]) -> dict:
    canonical_keys = {url.lower(): resolve_repo_url(url, renames) for url in renames.values()}
    merged = {}
    for sources in provider_data:
        for url, data in sorted(
            sources.items(), key=lambda item: (item[0].lower() != resolve_repo_url(item[0], renames).lower(), item[0])
        ):
            destination = resolve_repo_url(url, renames)
            key = canonical_keys.setdefault(destination.lower(), destination)
            entry = merged.setdefault(key, {})
            for field, value in data.items():
                entry.setdefault(field, value)
    return merged


def apply_source_config(repos_data: dict, custom_data: dict, renames: dict[str, str]) -> dict:
    effective_renames = dict(renames)
    for url, metadata in repos_data.items():
        if destination := metadata.get("renamedTo"):
            record_repo_rename(effective_renames, url, destination)
    configs = {url.lower(): data for url, data in merge_sources([custom_data], effective_renames).items()}
    resolved = {}
    for url, metadata in repos_data.items():
        config = configs.get(resolve_repo_url(url, effective_renames).lower(), {})
        resolved[url.lower()] = config
        if config.get("enabled") is False:
            metadata["enabled"] = False
        else:
            metadata.pop("enabled", None)
    return resolved
