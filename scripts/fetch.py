# Copyright (c) 2026 nvbangg (github.com/nvbangg)

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from http import HTTPStatus
from http.client import HTTPException

from utils import (
    BUNDLE_PARSER_DIR,
    BUNDLES_DIR,
    CONCURRENCY,
    DEFAULT_BRANCHES,
    MPP_DIR,
    PARSED_FILES_PATH,
    PATCHES_DIR,
    REPOS_JSON_PATH,
    UNAVAILABLE_HTTP_CODES,
    UPDATED_FILES_PATH,
    append_step_summary,
    build_raw_url,
    build_repo_url,
    extract_mpp_name,
    fetch,
    get_auth_headers,
    load_json,
    load_lines,
    parse_repo_url,
    save_json,
)

HASH_REQUEST_TIMEOUT_SECONDS = 10
GRADLE_EXECUTABLE_NAME = "gradlew.bat" if sys.platform == "win32" else "gradlew"
GRADLE_EXECUTABLE_PATH = BUNDLE_PARSER_DIR / GRADLE_EXECUTABLE_NAME


@dataclass
class BranchFetchResult:
    source: str
    repo: str
    branch: str
    new_sha: str | None
    status_changed: bool = False
    needs_parse: bool = False
    bundle_name: str | None = None
    error_message: str | None = None
    metadata_unavailable: bool = False

    @property
    def target_name(self) -> str:
        return f"{self.source}~{self.repo.replace('/', '~')}~{self.branch}"


def get_remote_file_hash(
    url: str, source: str, fallback: str | None = None
) -> str | None:
    try:
        request = urllib.request.Request(
            url, headers=get_auth_headers(url), method="HEAD"
        )
        with urllib.request.urlopen(
            request, timeout=HASH_REQUEST_TIMEOUT_SECONDS
        ) as response:
            header_name = "ETag" if source == "github" else "x-gitlab-content-sha256"
            if remote_hash := response.getheader(header_name):
                return remote_hash.strip('"')
            if fallback is not None:
                return fallback
            raise ValueError(f"Missing {header_name} header for {url}")
    except urllib.error.HTTPError as error:
        if error.code in UNAVAILABLE_HTTP_CODES:
            return None
        raise


def get_file_sha(source: str, repo: str, branch: str) -> str | None:
    url = build_raw_url(source, repo, branch, "patches-bundle.json")
    return get_remote_file_hash(url, source) if url else None


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
) -> BranchFetchResult:
    repo_url = build_repo_url(source, repo)

    def failed(
        message: str, unavailable: bool = False, metadata_unavailable: bool = False
    ) -> BranchFetchResult:
        error_message = f"{repo_url} ({branch}): {message}"
        print(f"[-] {error_message}")
        return BranchFetchResult(
            source,
            repo,
            branch,
            None if unavailable else current_sha,
            status_changed=unavailable,
            error_message=error_message,
            metadata_unavailable=metadata_unavailable,
        )

    try:
        remote_sha = get_file_sha(source, repo, branch)
    except (OSError, HTTPException, ValueError) as error:
        return failed(f"Failed to check metadata hash: {error}")

    file_prefix = f"{source}~{repo.replace('/', '~')}~{branch}"
    bundle_file = BUNDLES_DIR / f"{file_prefix}.json"
    patches_file = PATCHES_DIR / f"{file_prefix}.json"
    if not remote_sha:
        return failed(
            "Bundle metadata is unavailable (HTTP 404/451)",
            unavailable=True,
            metadata_unavailable=True,
        )
    if (
        current_sha
        and remote_sha == current_sha
        and bundle_file.is_file()
        and patches_file.is_file()
    ):
        if weekly:
            bundle_data = load_json(bundle_file)
            mpp_url = (
                bundle_data.get("download_url")
                if isinstance(bundle_data, dict)
                else None
            )
            if not isinstance(mpp_url, str) or not mpp_url:
                return failed("Invalid download_url", True)
            try:
                mpp_exists = get_remote_file_hash(mpp_url, source, fallback="exists")
            except (OSError, HTTPException, ValueError) as error:
                return failed(f"Failed to verify .mpp: {error}")
            if not mpp_exists:
                return failed(".mpp is unavailable (HTTP 404/451)", True)
        return BranchFetchResult(source, repo, branch, current_sha)

    bundle_url = build_raw_url(source, repo, branch, "patches-bundle.json")
    try:
        bundle_content = fetch(bundle_url, binary=True)
    except urllib.error.HTTPError as error:
        return failed(
            f"Failed to download metadata: {error}",
            unavailable=error.code in UNAVAILABLE_HTTP_CODES,
            metadata_unavailable=error.code in UNAVAILABLE_HTTP_CODES,
        )
    except (OSError, HTTPException) as error:
        return failed(f"Failed to download metadata: {error}")
    try:
        bundle_data = json.loads(bundle_content)
    except ValueError as error:
        return failed(f"Invalid patches-bundle.json: {error}", True)
    if not isinstance(bundle_data, dict):
        return failed("Invalid patches-bundle.json: expected an object", True)
    try:
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
        mpp_source, mpp_repo = (
            parse_repo_url(mpp_url)
            if isinstance(mpp_url, str) and mpp_url.lower().endswith(".mpp")
            else (None, None)
        )
        if mpp_source != source or not mpp_repo or mpp_repo.lower() != repo.lower():
            return failed(f"Invalid download_url: {mpp_url}", True)

    except ValueError as error:
        return failed(f"Invalid download_url: {error}", True)

    try:
        mpp_content = fetch(mpp_url, binary=True)
    except urllib.error.HTTPError as error:
        return failed(
            f"Failed to download .mpp: {error}",
            error.code in UNAVAILABLE_HTTP_CODES,
        )
    except (OSError, HTTPException) as error:
        return failed(f"Failed to download .mpp: {error}")
    bundle_name = extract_mpp_name(mpp_content)

    patches_url = get_patches_list_url(source, repo, branch)
    try:
        patches_content = fetch(patches_url, binary=True)
    except urllib.error.HTTPError as error:
        if error.code != HTTPStatus.NOT_FOUND:
            return failed(f"Failed to download patch list: {error}")
        patches_content = None
    except (OSError, HTTPException) as error:
        return failed(f"Failed to download patch list: {error}")

    save_json(bundle_file, bundle_data)
    MPP_DIR.mkdir(parents=True, exist_ok=True)
    (MPP_DIR / f"{file_prefix}.mpp").write_bytes(mpp_content)
    if patches_content is not None:
        patches_file.parent.mkdir(parents=True, exist_ok=True)
        patches_file.write_bytes(patches_content)
    return BranchFetchResult(
        source,
        repo,
        branch,
        remote_sha,
        status_changed=True,
        needs_parse=patches_content is None,
        bundle_name=bundle_name,
    )


def run_bundle_parser(targets: list[BranchFetchResult]) -> None:
    if not targets:
        UPDATED_FILES_PATH.unlink(missing_ok=True)
        return
    UPDATED_FILES_PATH.write_text(
        "\n".join(f"mpp/{target.target_name}.mpp" for target in targets),
        encoding="utf-8",
    )
    PARSED_FILES_PATH.unlink(missing_ok=True)
    print(f"\nParsing {len(targets)} bundles...")
    subprocess.run(
        [str(GRADLE_EXECUTABLE_PATH), "run", "--args=@updated_files.txt"],
        cwd=str(BUNDLE_PARSER_DIR),
        text=True,
        check=True,
    )
    if not PARSED_FILES_PATH.is_file():
        raise RuntimeError("bundle-parser did not write parsed_files.txt")
    successful_files = set(load_lines(PARSED_FILES_PATH))
    for target in targets:
        output_name = f"{target.target_name}.json"
        if output_name in successful_files and (PATCHES_DIR / output_name).is_file():
            continue
        target.new_sha = None
        target.bundle_name = None
        target.error_message = (
            f"{build_repo_url(target.source, target.repo)} ({target.branch}): "
            "Parser did not produce a confirmed patch list"
        )
        print(f"[-] {target.error_message}")


def process_image(
    source: str, repo: str, current_image: str | None
) -> tuple[str, str, str | None, bool, str | None]:
    repo_url = build_repo_url(source, repo)
    try:
        remote_sha = get_image_sha(source, repo)
    except (OSError, HTTPException, ValueError) as error:
        error_message = f"{repo_url}: Failed to fetch image: {error}"
        print(f"[-] {error_message}")
        return source, repo, current_image, False, error_message
    return source, repo, remote_sha, remote_sha != current_image, None


def collect_fetch_errors(results: list[BranchFetchResult]) -> list[str]:
    errors = []
    unavailable_branches: dict[tuple[str, str], set[str]] = {}
    for result in results:
        if result.metadata_unavailable:
            unavailable_branches.setdefault((result.source, result.repo), set()).add(
                result.branch
            )
        elif result.error_message:
            errors.append(result.error_message)
    for (source, repo), branches in unavailable_branches.items():
        if all(branch in branches for branch in DEFAULT_BRANCHES):
            errors.append(
                f"{build_repo_url(source, repo)}: patches-bundle.json is unavailable "
                f"on {' and '.join(DEFAULT_BRANCHES)} (HTTP 404/451)"
            )
    return errors


def fetch_all_repos(daily: bool = False, weekly: bool = False) -> None:
    repos_data = load_json(REPOS_JSON_PATH, {})
    BUNDLES_DIR.mkdir(parents=True, exist_ok=True)
    PATCHES_DIR.mkdir(parents=True, exist_ok=True)
    MPP_DIR.mkdir(parents=True, exist_ok=True)
    tasks = []
    image_tasks = []
    for repo, repo_metadata in repos_data.items():
        if not isinstance(repo_metadata, dict):
            continue
        for source in ("github", "gitlab"):
            if source_metadata := repo_metadata.get(source):
                for branch in DEFAULT_BRANCHES:
                    tasks.append((source, repo, branch, source_metadata.get(branch)))
                if daily or weekly:
                    image_tasks.append((source, repo, source_metadata.get("image")))

    print(f"Processing {len(tasks)} branch targets...")
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        futures = [
            executor.submit(process_repo_branch, *task, weekly=weekly) for task in tasks
        ]
        results = [future.result() for future in as_completed(futures)]
    results.sort(key=lambda result: (result.repo.lower(), result.source, result.branch))
    run_bundle_parser([result for result in results if result.needs_parse])
    errors = collect_fetch_errors(results)
    updated_count = 0
    for result in results:
        if not result.status_changed:
            continue
        updated_count += 1
        repo_metadata = repos_data[result.repo]
        repo_metadata[result.source][result.branch] = result.new_sha
        if result.new_sha and result.bundle_name:
            repo_metadata["name"] = result.bundle_name
    if image_tasks:
        print(f"Processing {len(image_tasks)} image targets...")
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
            image_futures = [
                executor.submit(process_image, *task) for task in image_tasks
            ]
            for future in as_completed(image_futures):
                source, repo, new_image_sha, status_changed, error_message = (
                    future.result()
                )
                if error_message:
                    errors.append(error_message)
                if status_changed:
                    updated_count += 1
                    repos_data[repo][source]["image"] = new_image_sha
    if updated_count:
        save_json(
            REPOS_JSON_PATH,
            dict(sorted(repos_data.items(), key=lambda item: item[0].lower())),
        )
    if errors:
        append_step_summary(
            "\n".join(["### ⚠️ Fetch", *[f"- {error}" for error in sorted(errors)]])
        )
    print(f"Fetch completed. Updated {updated_count} targets.")


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
