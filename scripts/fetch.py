# Copyright (c) 2026 nvbangg (github.com/nvbangg)

import argparse
import contextlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from utils import (
    BUNDLES_DIR,
    CONCURRENCY,
    DEFAULT_BRANCHES,
    MPP_DIR,
    PATCHES_DIR,
    PENDING_REPOS_PATH,
    REPOS_JSON_PATH,
    UNAVAILABLE_HTTP_CODES,
    UPDATED_FILES_PATH,
    append_step_summary,
    build_raw_url,
    build_repo_url,
    fetch,
    get_auth_headers,
    load_json,
    parse_repo_url,
    save_json,
)


def cleanup_target_files(file_prefix: str) -> None:
    (BUNDLES_DIR / f"{file_prefix}.json").unlink(missing_ok=True)
    (PATCHES_DIR / f"{file_prefix}.json").unlink(missing_ok=True)
    (MPP_DIR / f"{file_prefix}.mpp").unlink(missing_ok=True)


def extract_mpp_name(mpp_file: Path) -> str | None:
    with contextlib.suppress(Exception), zipfile.ZipFile(mpp_file, "r") as zip_file:
        manifest_text = zip_file.read("META-INF/MANIFEST.MF").decode("utf-8")
        for line in manifest_text.splitlines():
            if line.startswith("Name:"):
                return line.split(":", 1)[1].strip()
    return None


def get_remote_file_hash(
    url: str, source: str, fallback: str | None = None
) -> str | None:
    try:
        request = urllib.request.Request(
            url, headers=get_auth_headers(url), method="HEAD"
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            if source == "github":
                etag = response.getheader("ETag")
                return etag.strip('"') if etag else fallback
            if source == "gitlab":
                sha = response.getheader("x-gitlab-content-sha256")
                return sha or fallback
            return fallback
    except urllib.error.HTTPError as error:
        if error.code in UNAVAILABLE_HTTP_CODES:
            return None
        raise
    return None


def get_file_sha(source: str, repo: str, branch: str) -> str | None:
    url = build_raw_url(source, repo, branch, "patches-bundle.json")
    return get_remote_file_hash(url, source, fallback=None) if url else None


def get_patches_list_url(source: str, repo: str, branch: str) -> str | None:
    return build_raw_url(source, repo, branch, "patches-list.json")


def get_image_sha(source: str, repo: str) -> str | None:
    url = build_raw_url(source, repo, "main", "patches-bundle.png")
    return get_remote_file_hash(url, source, fallback="exists") if url else None


def process_repo_branch(
    source: str,
    repo: str,
    branch: str,
    current_sha: str | None,
    weekly: bool = False,
) -> tuple[
    str, str, str, str | None, str | None, bool, bool, bool, str | None, str | None
]:
    repo_url = build_repo_url(source, repo)
    try:
        remote_sha = get_file_sha(source, repo, branch)
    except Exception as error:
        error_message = f"{repo_url} ({branch}): Failed: {error}"
        print(f"[-] {error_message}")
        return (
            source,
            repo,
            branch,
            current_sha,
            None,
            False,
            False,
            False,
            None,
            error_message,
        )

    file_prefix = f"{source}~{repo.replace('/', '~')}~{branch}"
    bundle_file = BUNDLES_DIR / f"{file_prefix}.json"
    patches_file = PATCHES_DIR / f"{file_prefix}.json"

    if remote_sha == current_sha and bundle_file.exists() and patches_file.exists():
        if weekly and current_sha:
            bundle_data = load_json(bundle_file, {})
            if mpp_url := bundle_data.get("download_url"):
                try:
                    mpp_exists = bool(
                        get_remote_file_hash(mpp_url, source, fallback="exists")
                    )
                except Exception as error:
                    error_message = (
                        f"{repo_url} ({branch}): Failed to verify `.mpp`: {error}"
                    )
                    print(f"[-] {error_message}")
                    return (
                        source,
                        repo,
                        branch,
                        current_sha,
                        None,
                        False,
                        False,
                        False,
                        None,
                        error_message,
                    )

                if not mpp_exists:
                    print(
                        f"[-] {repo_url} ({branch}): `.mpp` file is no longer available"
                    )
                    cleanup_target_files(file_prefix)
                    return (
                        source,
                        repo,
                        branch,
                        remote_sha,
                        None,
                        False,
                        True,
                        True,
                        None,
                        None,
                    )

        return (
            source,
            repo,
            branch,
            remote_sha,
            None,
            False,
            False,
            False,
            None,
            None,
        )

    if remote_sha is None:
        print(f"[-] {repo_url} ({branch}): `patches-bundle.json` not found")
        return source, repo, branch, None, None, False, True, True, None, None

    raw_bundle_url = build_raw_url(source, repo, branch, "patches-bundle.json")
    if not raw_bundle_url:
        return (
            source,
            repo,
            branch,
            current_sha,
            None,
            False,
            False,
            False,
            None,
            None,
        )

    try:
        bundle_text = fetch(raw_bundle_url)
    except Exception as error:
        if (
            isinstance(error, urllib.error.HTTPError)
            and error.code in UNAVAILABLE_HTTP_CODES
        ):
            print(
                f"[-] {repo_url} ({branch}): `patches-bundle.json` not found or taken down (HTTP {error.code})"
            )
            return (
                source,
                repo,
                branch,
                remote_sha,
                None,
                False,
                True,
                True,
                None,
                None,
            )
        error_message = f"{repo_url} ({branch}): Failed: {error}"
        print(f"[-] {error_message}")
        return (
            source,
            repo,
            branch,
            current_sha,
            None,
            False,
            False,
            False,
            None,
            error_message,
        )

    has_mpp = False
    bundle_name = None
    try:
        bundle_data = json.loads(bundle_text)
        mpp_url = bundle_data.get("download_url")
        if source == "gitlab" and isinstance(mpp_url, str):
            parsed_url = urllib.parse.urlparse(mpp_url)
            path_parts = parsed_url.path.split("/")
            if (
                len(path_parts) > 5
                and path_parts[1:4] == ["api", "v4", "projects"]
                and path_parts[4].isdigit()
            ):
                path_parts[4] = urllib.parse.quote(repo, safe="")
                mpp_url = urllib.parse.urlunparse(
                    parsed_url._replace(path="/".join(path_parts))
                )
                bundle_data["download_url"] = mpp_url
                bundle_text = json.dumps(bundle_data)
        mpp_source, mpp_repo = (
            parse_repo_url(mpp_url)
            if isinstance(mpp_url, str) and mpp_url.lower().endswith(".mpp")
            else (None, None)
        )
        if mpp_source != source or mpp_repo.lower() != repo.lower():
            print(f"[-] {repo_url} ({branch}): Invalid `download_url`")
            cleanup_target_files(file_prefix)
            return (
                source,
                repo,
                branch,
                remote_sha,
                bundle_text,
                False,
                True,
                True,
                None,
                None,
            )

        mpp_file_path = MPP_DIR / f"{file_prefix}.mpp"
        try:
            mpp_bytes = fetch(mpp_url, binary=True)
            MPP_DIR.mkdir(parents=True, exist_ok=True)
            mpp_file_path.write_bytes(mpp_bytes)
            has_mpp = True
            bundle_name = extract_mpp_name(mpp_file_path)
        except Exception as error:
            if (
                isinstance(error, urllib.error.HTTPError)
                and error.code in UNAVAILABLE_HTTP_CODES
            ):
                print(
                    f"[-] {repo_url} ({branch}): `.mpp` file not found or taken down (HTTP {error.code})"
                )
                cleanup_target_files(file_prefix)
                return (
                    source,
                    repo,
                    branch,
                    remote_sha,
                    bundle_text,
                    False,
                    True,
                    True,
                    None,
                    None,
                )
            error_message = f"{repo_url} ({branch}): Failed: {error}"
            print(f"[-] {error_message}")
            return (
                source,
                repo,
                branch,
                current_sha,
                None,
                False,
                False,
                False,
                None,
                error_message,
            )
    except Exception:
        pass

    return (
        source,
        repo,
        branch,
        remote_sha,
        bundle_text,
        has_mpp,
        True,
        False,
        bundle_name,
        None,
    )


def process_image(
    source: str, repo: str, current_image: str | None
) -> tuple[str, str, str | None, bool, str | None]:
    repo_url = build_repo_url(source, repo)
    try:
        remote_sha = get_image_sha(source, repo)
    except Exception as error:
        if (
            isinstance(error, urllib.error.HTTPError)
            and error.code in UNAVAILABLE_HTTP_CODES
        ):
            return source, repo, None, current_image is not None, None
        error_message = f"{repo_url}: Failed to fetch image: {error}"
        print(f"[-] {error_message}")
        return source, repo, current_image, False, error_message

    if remote_sha == current_image:
        return source, repo, remote_sha, False, None
    return source, repo, remote_sha, True, None


def fetch_all_repos(daily: bool = False, weekly: bool = False) -> None:
    repos_data = load_json(REPOS_JSON_PATH, {})

    BUNDLES_DIR.mkdir(parents=True, exist_ok=True)
    PATCHES_DIR.mkdir(parents=True, exist_ok=True)
    MPP_DIR.mkdir(parents=True, exist_ok=True)

    tasks = []
    image_tasks = []
    is_daily = daily or weekly
    for repo, repo_metadata in repos_data.items():
        if not isinstance(repo_metadata, dict):
            continue
        for source in ("github", "gitlab"):
            if source_metadata := repo_metadata.get(source):
                for branch in DEFAULT_BRANCHES:
                    current_sha = source_metadata.get(branch)
                    tasks.append((source, repo, branch, current_sha))
                if is_daily:
                    image_tasks.append((source, repo, source_metadata.get("image")))

    print(f"Processing {len(tasks)} branch targets...")
    pending_repos_data = {}
    updated_count = 0
    updated_files = []
    errors = []

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        futures = [
            executor.submit(
                process_repo_branch, source, repo, branch, current_sha, weekly
            )
            for source, repo, branch, current_sha in tasks
        ]

        for future in as_completed(futures):
            (
                source,
                repo,
                branch,
                new_sha,
                bundle_text,
                has_mpp,
                status_changed,
                is_unavailable,
                bundle_name,
                error_message,
            ) = future.result()
            if error_message:
                errors.append(error_message)

            if not status_changed:
                continue

            updated_count += 1
            pending_repos_data.setdefault(repo, {}).setdefault(source, {})[branch] = (
                new_sha
            )
            if bundle_name:
                pending_repos_data.setdefault(repo, {})["name"] = bundle_name

            file_prefix = f"{source}~{repo.replace('/', '~')}~{branch}"
            if not is_unavailable and new_sha is not None:
                if bundle_text:
                    save_json(
                        BUNDLES_DIR / f"{file_prefix}.json",
                        json.loads(bundle_text),
                    )

                has_patch_list = False
                if patches_list_url := get_patches_list_url(source, repo, branch):
                    with contextlib.suppress(Exception):
                        content = fetch(patches_list_url)
                        save_json(
                            PATCHES_DIR / f"{file_prefix}.json",
                            json.loads(content),
                        )
                        has_patch_list = True

                if not has_patch_list and has_mpp:
                    updated_files.append(f"mpp/{file_prefix}.mpp")

    if is_daily:
        print(f"Processing {len(image_tasks)} image targets...")
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
            image_futures = [
                executor.submit(process_image, source, repo, current_image)
                for source, repo, current_image in image_tasks
            ]
            for future in as_completed(image_futures):
                source, repo, new_image_sha, status_changed, error_message = (
                    future.result()
                )
                if error_message:
                    errors.append(error_message)

                if status_changed:
                    updated_count += 1
                    pending_repos_data.setdefault(repo, {}).setdefault(source, {})[
                        "image"
                    ] = new_image_sha

    if errors:
        markdown_lines = ["### ⚠️ Fetch", *[f"- {error}" for error in sorted(errors)]]
        append_step_summary("\n".join(markdown_lines))

    print(f"Fetch completed. Updated {updated_count} targets.")

    if updated_files:
        UPDATED_FILES_PATH.write_text("\n".join(updated_files), encoding="utf-8")
        print(
            f"Saved {len(updated_files)} updated targets to updated_files.txt and pending_repos.json"
        )
    elif UPDATED_FILES_PATH.exists():
        UPDATED_FILES_PATH.unlink()

    save_json(PENDING_REPOS_PATH, pending_repos_data)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Morphe patches bundles")
    parser.add_argument("--daily", action="store_true", help="Daily sync")
    parser.add_argument(
        "--weekly",
        action="store_true",
        help="Weekly sync to check bundles availability",
    )
    args = parser.parse_args()
    fetch_all_repos(daily=args.daily, weekly=args.weekly)


if __name__ == "__main__":
    sys.exit(main())
