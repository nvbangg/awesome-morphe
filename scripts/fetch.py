# Copyright (c) 2026 nvbangg (github.com/nvbangg)

import contextlib
import io
import re
import subprocess
import sys
import urllib.parse
import zipfile
import zlib
from collections.abc import Iterable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from http import HTTPStatus
from threading import Lock

import httpx2
from pydantic import ValidationError

from common.constants import (
    BUNDLES_DIR,
    CONCURRENCY,
    DEFAULT_BRANCHES,
    DISCOVERY_JSON_PATH,
    PATCHES_DIR,
    REPOS_JSON_PATH,
    SCRIPTS_DIR,
    UNAVAILABLE_HTTP_CODES,
)
from common.files import load_json, save_json
from common.http import request
from common.images import normalize_image_url
from common.models import BUNDLE_MANIFEST, DISCOVERY, REPOSITORIES
from common.repositories import (
    build_raw_url,
    build_repo_url,
    fetch_repo_details,
    parse_repo_url,
)
from common.summary import append_step_summary, format_summary_section

BUNDLE_PARSER_DIR = SCRIPTS_DIR / "bundle-parser"
MPP_DIR = BUNDLE_PARSER_DIR / "mpp"
UPDATED_FILES_PATH = BUNDLE_PARSER_DIR / "updated_files.txt"
PARSED_FILES_PATH = BUNDLE_PARSER_DIR / "parsed_files.txt"
GRADLE_EXECUTABLE_NAME = "gradlew.bat" if sys.platform == "win32" else "gradlew"
GRADLE_EXECUTABLE_PATH = BUNDLE_PARSER_DIR / GRADLE_EXECUTABLE_NAME
FETCH_ERROR_SECTIONS = {
    "repo_metadata": "Repository metadata",
    "metadata": "Bundle metadata",
    "bundle": "Bundle download",
    "patch_list": "Patch list",
    "image": "Bundle image",
}
HASH_REQUEST_HEADERS = {"Accept-Encoding": "identity"}


def extract_mpp_name(mpp_file: bytes) -> str | None:
    with (
        contextlib.suppress(
            zipfile.BadZipFile,
            KeyError,
            UnicodeDecodeError,
            EOFError,
            OSError,
            RuntimeError,
            zlib.error,
        ),
        zipfile.ZipFile(io.BytesIO(mpp_file), "r") as zip_file,
    ):
        manifest_text = zip_file.read("META-INF/MANIFEST.MF").decode("utf-8")
        for line in manifest_text.splitlines():
            if line.startswith("Name:"):
                return line.split(":", 1)[1].strip()
    return None


class BundleDownloads:
    def __init__(self) -> None:
        self.futures: dict[str, Future[bytes]] = {}
        self.lock = Lock()

    def download(self, url: str) -> bytes:
        with self.lock:
            future = self.futures.get(url)
            if future is None:
                future = Future()
                self.futures[url] = future
                owns_download = True
            else:
                owns_download = False
        if owns_download:
            try:
                future.set_result(request(url).content)
            except BaseException as error:
                future.set_exception(error)
                raise
        return future.result()


class RepositoryDetails:
    def __init__(self) -> None:
        self.futures: dict[str, Future[dict]] = {}
        self.lock = Lock()

    def get(self, url: str) -> dict:
        key = url.lower()
        with self.lock:
            future = self.futures.get(key)
            if future is None:
                future = Future()
                self.futures[key] = future
                owns_request = True
            else:
                owns_request = False
        if owns_request:
            try:
                future.set_result(fetch_repo_details(url))
            except BaseException as error:
                future.set_exception(error)
                raise
        return future.result()


@dataclass
class BranchFetchResult:
    source: str
    repo: str
    branch: str
    new_sha: str | None
    repo_id: str
    status_changed: bool = False
    needs_parse: bool = False
    bundle_name: str | None = None
    error_message: str | None = None
    error_category: str | None = None

    @property
    def target_name(self) -> str:
        return f"{self.repo_id.replace(':', '-')}-{self.branch}"


def get_remote_file_hash(url: str, source: str, fallback: str | None = None) -> str:
    response = request(url, HASH_REQUEST_HEADERS, "HEAD")
    header_name = "ETag" if source == "github" else "x-gitlab-content-sha256"
    if remote_hash := response.headers.get(header_name):
        return remote_hash.removeprefix("W/").strip('"')
    if fallback is not None:
        return fallback
    raise ValueError(f"Missing `{header_name}` header")


def get_github_bundle(url: str, current_sha: str | None) -> tuple[str, bytes | None]:
    headers = dict(HASH_REQUEST_HEADERS)
    if current_sha:
        headers["If-None-Match"] = f'"{current_sha}"'
    try:
        response = request(url, headers)
        remote_hash = response.headers.get("ETag")
        if not remote_hash:
            raise ValueError("Missing `ETag` header")
        return remote_hash.removeprefix("W/").strip('"'), response.content
    except httpx2.HTTPStatusError as error:
        if error.response.status_code == HTTPStatus.NOT_MODIFIED and current_sha:
            return current_sha, None
        raise


def process_repo_branch(
    source: str,
    repo: str,
    branch: str,
    current_sha: str | None,
    repo_id: str,
    daily: bool = False,
    bundle_downloads: BundleDownloads | None = None,
    repository_details: RepositoryDetails | None = None,
) -> BranchFetchResult:
    def failed(message: str, category: str, unavailable: bool = False) -> BranchFetchResult:
        return BranchFetchResult(
            source,
            repo,
            branch,
            None if unavailable else current_sha,
            status_changed=unavailable,
            error_message=message,
            error_category=category,
            repo_id=repo_id,
        )

    file_prefix = f"{repo_id.replace(':', '-')}-{branch}"
    bundle_file = BUNDLES_DIR / f"{file_prefix}.json"
    patches_file = PATCHES_DIR / f"{file_prefix}.json"
    has_local_data = bundle_file.is_file() and patches_file.is_file()
    bundle_url = build_raw_url(source, repo, branch, "patches-bundle.json")
    if not bundle_url:
        return failed("Metadata hash is unavailable", "metadata", True)
    bundle_content = None
    try:
        if source == "github":
            remote_sha, bundle_content = get_github_bundle(bundle_url, current_sha if has_local_data else None)
        else:
            remote_sha = get_remote_file_hash(bundle_url, source)
    except httpx2.HTTPStatusError as error:
        return failed(
            str(error),
            "metadata",
            error.response.status_code in UNAVAILABLE_HTTP_CODES,
        )
    except (OSError, httpx2.HTTPError, httpx2.InvalidURL, ValueError) as error:
        return failed(str(error), "metadata")

    if not remote_sha:
        return failed(
            "Metadata hash is unavailable",
            "metadata",
            True,
        )
    if current_sha and remote_sha == current_sha and has_local_data:
        if daily:
            try:
                mpp_url = BUNDLE_MANIFEST.validate_python(load_json(bundle_file))["download_url"]
            except ValidationError:
                return failed("Invalid `download_url`", "metadata", True)
            try:
                get_remote_file_hash(mpp_url, source, "exists")
            except httpx2.HTTPStatusError as error:
                return failed(
                    str(error),
                    "bundle",
                    error.response.status_code in UNAVAILABLE_HTTP_CODES,
                )
            except (OSError, httpx2.HTTPError, httpx2.InvalidURL, ValueError) as error:
                return failed(str(error), "bundle")
        return BranchFetchResult(source, repo, branch, current_sha, repo_id=repo_id)

    try:
        if bundle_content is None:
            bundle_content = request(bundle_url).content
    except httpx2.HTTPStatusError as error:
        return failed(
            str(error),
            "metadata",
            error.response.status_code in UNAVAILABLE_HTTP_CODES,
        )
    except (OSError, httpx2.HTTPError, httpx2.InvalidURL) as error:
        return failed(str(error), "metadata")
    try:
        bundle_data = BUNDLE_MANIFEST.validate_json(bundle_content)
    except ValueError:
        return failed("Invalid data", "metadata", True)
    try:
        mpp_url = bundle_data["download_url"]
        if not mpp_url.lower().endswith(".mpp"):
            return failed("Invalid `download_url`", "metadata", True)
        parsed_url = urllib.parse.urlsplit(mpp_url)
        if parsed_url.scheme != "https":
            return failed("Invalid `download_url`", "metadata", True)
        project_match = (
            re.match(r"/(?:api/v4/projects|-/project)/(\d+)/", parsed_url.path)
            if source == "gitlab" and parsed_url.hostname == "gitlab.com"
            else None
        )
        mpp_source, mpp_repo = (source, project_match[1]) if project_match else parse_repo_url(mpp_url)
        if mpp_source != source or not mpp_repo:
            return failed("Invalid `download_url`", "metadata", True)
        if project_match:
            if f"gitlab:{project_match[1]}" != repo_id:
                return failed("Invalid `download_url`", "metadata", True)
        elif mpp_repo.lower() != repo.lower():
            repository_details = repository_details or RepositoryDetails()
            download_repo_url = build_repo_url(source, mpp_repo)
            assert download_repo_url is not None
            details = repository_details.get(download_repo_url)
            if details.get("error") or not details.get("id"):
                return failed(details.get("error") or "Could not verify repository identity", "metadata")
            if details["id"] != repo_id:
                return failed("Invalid `download_url`", "metadata", True)

    except ValueError:
        return failed("Invalid `download_url`", "metadata", True)

    try:
        mpp_content = bundle_downloads.download(mpp_url) if bundle_downloads is not None else request(mpp_url).content
    except httpx2.HTTPStatusError as error:
        return failed(
            str(error),
            "bundle",
            error.response.status_code in UNAVAILABLE_HTTP_CODES,
        )
    except (OSError, httpx2.HTTPError, httpx2.InvalidURL) as error:
        return failed(str(error), "bundle")
    bundle_name = extract_mpp_name(mpp_content)

    patches_url = build_raw_url(source, repo, branch, "patches-list.json")
    assert patches_url is not None
    try:
        patches_content = request(patches_url).content
    except httpx2.HTTPStatusError as error:
        if error.response.status_code != HTTPStatus.NOT_FOUND:
            return failed(str(error), "patch_list")
        patches_content = None
    except (OSError, httpx2.HTTPError, httpx2.InvalidURL) as error:
        return failed(str(error), "patch_list")

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
        repo_id=repo_id,
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
        [str(GRADLE_EXECUTABLE_PATH), "run", "--args=updated_files.txt"],
        cwd=str(BUNDLE_PARSER_DIR),
        text=True,
        check=True,
    )
    if not PARSED_FILES_PATH.is_file():
        raise RuntimeError("bundle-parser did not write parsed_files.txt")
    successful_files = set(PARSED_FILES_PATH.read_text(encoding="utf-8").splitlines())
    for target in targets:
        output_name = f"{target.target_name}.json"
        if output_name in successful_files and (PATCHES_DIR / output_name).is_file():
            continue
        target.new_sha = None
        target.bundle_name = None
        target.error_category = "patch_list"
        target.error_message = "Failed to generate `patches-list.json`"


def process_image(source: str, repo: str, current_image: str | None) -> tuple[str, str, str | None, bool, str | None]:
    repo_url = build_repo_url(source, repo)
    try:
        image_url = build_raw_url(source, repo, "main", "patches-bundle.png")
        remote_sha = get_remote_file_hash(image_url, source, "exists") if image_url else None
    except (OSError, httpx2.HTTPError, httpx2.InvalidURL, ValueError) as error:
        if isinstance(error, httpx2.HTTPStatusError) and error.response.status_code in UNAVAILABLE_HTTP_CODES:
            return source, repo, None, current_image is not None, None
        return source, repo, current_image, False, f"{repo_url}: {error}"
    return source, repo, remote_sha, remote_sha != current_image, None


def collect_fetch_errors(results: Iterable[BranchFetchResult]) -> dict[str, list[str]]:
    errors = {category: [] for category in FETCH_ERROR_SECTIONS}
    grouped_results: dict[tuple[str, str], list[BranchFetchResult]] = {}
    for result in results:
        grouped_results.setdefault((result.source, result.repo), []).append(result)
    expected_branches = set(DEFAULT_BRANCHES)
    for (source, repo), branch_results in grouped_results.items():
        if {result.branch for result in branch_results} != expected_branches or any(
            not result.error_message for result in branch_results
        ):
            continue
        repo_url = build_repo_url(source, repo)
        first_result = branch_results[0]
        assert first_result.error_category is not None
        if all(
            (result.error_category, result.error_message) == (first_result.error_category, first_result.error_message)
            for result in branch_results
        ):
            errors[first_result.error_category].append(f"{repo_url}: {first_result.error_message}")
        else:
            category_errors: dict[str, list[str]] = {}
            for result in sorted(branch_results, key=lambda result: DEFAULT_BRANCHES.index(result.branch)):
                assert result.error_category is not None
                category_errors.setdefault(result.error_category, []).append(
                    f"({result.branch}) {result.error_message}"
                )
            for category, reasons in category_errors.items():
                errors[category].append(f"{repo_url}: {'; '.join(reasons)}")
    return errors


def refresh_repo_metadata(
    discovered: dict, existing: dict, repository_details: RepositoryDetails
) -> tuple[dict, list[tuple[str, str]], set[str]]:
    repositories = {}
    warnings = []
    failed_ids = set()
    unavailable_ids = set()
    configs = {}
    resolved_ids = set()
    disabled_ids = {entry["id"] for entry in discovered.values() if entry.get("enabled") is False and entry.get("id")}
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        futures = {
            url: executor.submit(repository_details.get, url)
            for url, entry in discovered.items()
            if entry.get("id") not in disabled_ids
        }
        for url, entry in discovered.items():
            config = {field: entry[field] for field in ("enabled", "revancedStars") if field in entry}
            source, repo = parse_repo_url(url)
            if not source:
                continue
            if url not in futures:
                repo_id = entry["id"]
                repositories.setdefault(repo_id, dict(existing.get(repo_id, {"repo": repo})))
                configs[repo_id] = config
                continue
            details = futures[url].result()
            repo_id = details.get("id")
            if not repo_id or details.get("error"):
                if config.get("enabled") is not False:
                    warnings.append((url, details.get("error") or "Invalid repository data"))
                repo_id = entry.get("id")
                if repo_id in existing:
                    metadata = repositories.setdefault(repo_id, dict(existing[repo_id]))
                    failed_ids.add(repo_id)
                    if details.get("is_404") or details.get("is_451"):
                        unavailable_ids.add(repo_id)
                else:
                    continue
            else:
                entry["id"] = repo_id
                metadata = repositories.setdefault(repo_id, dict(existing.get(repo_id, {})))
                metadata.update(
                    repo=details["full_name"],
                    description=details.get("description") or "",
                    avatarUrl=normalize_image_url(details.get("avatar_url")),
                    stars=details.get("stars", 0),
                )
                if details.get("is_archived"):
                    metadata["isArchived"] = True
                    warnings.append((url, "Repository is archived"))
                else:
                    metadata.pop("isArchived", None)
                resolved_ids.add(repo_id)
            if config.get("enabled") is False:
                disabled_ids.add(repo_id)
            configs[repo_id] = config
    for repo_id in unavailable_ids - resolved_ids:
        repositories[repo_id].update({branch: None for branch in DEFAULT_BRANCHES})
    for repo_id, config in configs.items():
        repositories[repo_id].pop("enabled", None)
        repositories[repo_id].pop("revancedStars", None)
        repositories[repo_id].update(config)
        if repo_id in disabled_ids:
            repositories[repo_id]["enabled"] = False
    warnings = [
        (url, message)
        for url, message in warnings
        if repositories.get(discovered[url].get("id"), {}).get("enabled") is not False
    ]
    return repositories, warnings, failed_ids - resolved_ids


def fetch_all_repos(daily: bool = False) -> None:
    initial_discovery = load_json(DISCOVERY_JSON_PATH, {"providers": {}, "repositories": {}})
    registry = DISCOVERY.validate_python(initial_discovery)
    discovered = registry["repositories"]
    if not discovered:
        raise ValueError("No discovered repositories; fetch stopped")
    initial_repos = REPOSITORIES.validate_python(load_json(REPOS_JSON_PATH))
    repository_details = RepositoryDetails()
    repos_data, repository_warnings, failed_ids = refresh_repo_metadata(discovered, initial_repos, repository_details)
    BUNDLES_DIR.mkdir(parents=True, exist_ok=True)
    PATCHES_DIR.mkdir(parents=True, exist_ok=True)
    MPP_DIR.mkdir(parents=True, exist_ok=True)
    tasks = []
    for repo_id, metadata in repos_data.items():
        if metadata.get("enabled") is False or repo_id in failed_ids:
            continue
        source = repo_id.split(":", 1)[0]
        for branch in DEFAULT_BRANCHES:
            tasks.append((source, metadata["repo"], branch, metadata.get(branch), repo_id))
    print(f"Processing {len(tasks)} branch targets...")
    bundle_downloads = BundleDownloads()
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        futures = (
            executor.submit(
                process_repo_branch,
                *task,
                daily=daily,
                bundle_downloads=bundle_downloads,
                repository_details=repository_details,
            )
            for task in tasks
        )
        results = [future.result() for future in as_completed(futures)]
    results.sort(key=lambda result: (result.repo.lower(), result.source, DEFAULT_BRANCHES.index(result.branch)))
    run_bundle_parser([result for result in results if result.needs_parse])
    updated_count = 0
    grouped_results = {}
    for result in results:
        metadata = repos_data[result.repo_id]
        grouped_results.setdefault(result.repo_id, []).append(result)
        if result.status_changed:
            metadata[result.branch] = result.new_sha
            updated_count += 1
    for repo_id, branch_results in grouped_results.items():
        metadata = repos_data[repo_id]
        preferred = next((branch for branch in DEFAULT_BRANCHES if metadata.get(branch)), None)
        if not preferred:
            continue
        chosen = next(result for result in branch_results if result.branch == preferred)
        if chosen.error_message:
            continue
        previous = initial_repos.get(repo_id, {})
        previous_preferred = next((branch for branch in DEFAULT_BRANCHES if previous.get(branch)), None)
        if chosen.bundle_name:
            metadata["name"] = chosen.bundle_name
        elif chosen.status_changed:
            metadata["name"] = metadata.get("name") or ""
        elif previous_preferred != preferred or metadata.get("name") is None:
            local_mpp = MPP_DIR / f"{chosen.target_name}.mpp"
            try:
                content = (
                    local_mpp.read_bytes()
                    if local_mpp.is_file()
                    else bundle_downloads.download(
                        load_json(BUNDLES_DIR / f"{chosen.target_name}.json")["download_url"]
                    )
                )
                metadata["name"] = extract_mpp_name(content) or metadata.get("name") or ""
            except (OSError, httpx2.HTTPError, httpx2.InvalidURL) as error:
                print(f"[warning] {build_repo_url(chosen.source, chosen.repo)}: Failed to read bundle name: {error}")
    image_errors = []
    if daily:
        image_ids = list(grouped_results)
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
            futures = [
                executor.submit(
                    process_image,
                    repo_id.split(":", 1)[0],
                    repos_data[repo_id]["repo"],
                    repos_data[repo_id].get("image"),
                )
                for repo_id in image_ids
            ]
            for repo_id, future in zip(image_ids, futures):
                _source, _repo, image_sha, changed, error = future.result()
                if changed:
                    repos_data[repo_id]["image"] = image_sha
                    updated_count += 1
                if error:
                    image_errors.append(error)
    if repos_data != initial_repos:
        save_json(REPOS_JSON_PATH, dict(sorted(repos_data.items())))
    if registry != initial_discovery:
        save_json(DISCOVERY_JSON_PATH, registry)
    errors = collect_fetch_errors(results)
    errors["image"].extend(image_errors)
    errors["repo_metadata"].extend(f"{url}: {message}" for url, message in dict.fromkeys(repository_warnings))
    total_repo_count = sum(metadata.get("enabled") is not False for metadata in repos_data.values())
    successful_repo_count = sum(
        any(result.new_sha and not result.error_message for result in branch_results)
        for branch_results in grouped_results.values()
    )
    summary_sections = [f"## 📥 Fetch ({successful_repo_count}/{total_repo_count}):"]
    for category, title in FETCH_ERROR_SECTIONS.items():
        if not errors[category]:
            continue
        sorted_errors = sorted(errors[category], key=str.lower)
        print(f"[warning] {title}: {len(sorted_errors)} repositories with issues")
        content = "\n".join(f"- {error}" for error in sorted_errors)
        summary_sections.append(
            format_summary_section(
                title, content, len(sorted_errors), display="details-open" if category == "patch_list" else "details"
            )
        )
    append_step_summary("\n\n".join(summary_sections))
    print(f"Fetch completed. Updated {updated_count} targets.")
