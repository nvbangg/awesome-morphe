import io
import json
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import call, patch

import httpx2
import pytest

import fetch as bundle_fetch
from common.constants import DEFAULT_BRANCHES
from common.files import load_json, save_json
from common.repositories import build_raw_url, parse_repo_url

PATCH_LIST_BARRIER_TIMEOUT_SECONDS = 5
DOWNLOAD_WAIT_TIMEOUT_SECONDS = 5
HTTP_NOT_FOUND = 404


class TestGithubBundle:
    @pytest.fixture(autouse=True)
    def prepare(self, block_network) -> None:
        url = build_raw_url("github", "owner/alpha", "main", "patches-bundle.json")
        assert url is not None
        self.url = url
        self.open_url = block_network
        self.open_url.side_effect = None
        self.response = httpx2.Response(
            200,
            headers={"ETag": '"new-hash"'},
            content=b'{"download_url": "bundle.mpp"}',
        )
        self.open_url.return_value = self.response

    @pytest.mark.parametrize("etag", ('"new-hash"', 'W/"new-hash"'))
    def test_changed_metadata_uses_one_conditional_get_with_response_etag(self, etag) -> None:
        self.response.headers["ETag"] = etag
        result = bundle_fetch.get_github_bundle(self.url, "old-hash")
        assert result == ("new-hash", self.response.content)
        self.open_url.assert_called_once()
        request = self.open_url.call_args.args[0]
        assert request.method == "GET"
        assert request.headers["Accept-Encoding"] == "identity"
        assert request.headers["If-None-Match"] == '"old-hash"'

    def test_unconfirmed_metadata_uses_unconditional_get(self) -> None:
        bundle_fetch.get_github_bundle(self.url, None)
        assert self.open_url.call_args.args[0].headers.get("If-None-Match") is None

    def test_not_modified_preserves_hash_without_returning_body(self) -> None:
        self.open_url.return_value = httpx2.Response(304)
        assert bundle_fetch.get_github_bundle(self.url, "old-hash") == (
            "old-hash",
            None,
        )
        self.open_url.assert_called_once()

    def test_missing_etag_is_reported(self) -> None:
        self.response.headers.clear()
        with pytest.raises(ValueError, match="Missing `ETag`"):
            bundle_fetch.get_github_bundle(self.url, None)


@pytest.mark.parametrize("failure", (None, httpx2.ConnectError("Download failed")))
def test_concurrent_targets_share_download_without_blocking_other_urls(
    failure: BaseException | None,
) -> None:
    shared_url = "https://example.com/shared.mpp"
    other_url = "https://example.com/other.mpp"
    download_started = threading.Event()
    release_download = threading.Event()
    downloads = bundle_fetch.BundleDownloads()

    def download(url: str) -> httpx2.Response:
        if url == shared_url:
            download_started.set()
            assert release_download.wait(timeout=DOWNLOAD_WAIT_TIMEOUT_SECONDS)
            if failure is not None:
                raise failure
        return httpx2.Response(200, content=url.encode())

    with (
        patch.object(bundle_fetch, "request", side_effect=download) as request,
        ThreadPoolExecutor(max_workers=3) as executor,
    ):
        first = executor.submit(downloads.download, shared_url)
        try:
            assert download_started.wait(timeout=DOWNLOAD_WAIT_TIMEOUT_SECONDS)
            second = executor.submit(downloads.download, shared_url)
            other = executor.submit(downloads.download, other_url)
            assert other.result(timeout=DOWNLOAD_WAIT_TIMEOUT_SECONDS) == other_url.encode()
        finally:
            release_download.set()
        for result in (first, second):
            if failure is None:
                assert result.result(timeout=DOWNLOAD_WAIT_TIMEOUT_SECONDS) == shared_url.encode()
            else:
                with pytest.raises(type(failure)) as raised:
                    result.result(timeout=DOWNLOAD_WAIT_TIMEOUT_SECONDS)
                assert raised.value is failure
    assert request.call_count == 2


def test_repository_lookup_is_shared_without_blocking_other_urls() -> None:
    shared_url = "https://github.com/owner/old"
    other_url = "https://github.com/owner/other"
    details = {"full_name": "owner/new"}
    started = threading.Event()
    release = threading.Event()
    cache = bundle_fetch.RepositoryDetails()

    def lookup(url: str) -> dict:
        if url == shared_url:
            started.set()
            assert release.wait(timeout=DOWNLOAD_WAIT_TIMEOUT_SECONDS)
        return details

    with (
        patch.object(bundle_fetch, "fetch_repo_details", side_effect=lookup) as request,
        ThreadPoolExecutor(max_workers=3) as executor,
    ):
        first = executor.submit(cache.get, shared_url)
        try:
            assert started.wait(timeout=DOWNLOAD_WAIT_TIMEOUT_SECONDS)
            second = executor.submit(cache.get, shared_url.upper())
            other = executor.submit(cache.get, other_url)
            assert other.result(timeout=DOWNLOAD_WAIT_TIMEOUT_SECONDS) == details
        finally:
            release.set()
        assert first.result(timeout=DOWNLOAD_WAIT_TIMEOUT_SECONDS) == details
        assert second.result(timeout=DOWNLOAD_WAIT_TIMEOUT_SECONDS) == details
    assert request.call_count == 2


class TestBundleFetch:
    @pytest.fixture(autouse=True)
    def prepare(self, tmp_path: Path, patch_context, http_error) -> None:
        self.patch_context = patch_context
        self.http_error = http_error
        self.root = tmp_path
        self.parser_dir = self.root / "bundle-parser"
        self.parser_dir.mkdir()
        self.bundles_dir = self.root / "bundles"
        self.patches_dir = self.root / "patches"
        self.mpp_dir = self.parser_dir / "mpp"
        self.repos_path = self.root / "repos.json"
        self.updated_path = self.parser_dir / "updated_files.txt"
        self.parsed_path = self.parser_dir / "parsed_files.txt"
        self.initial_repos: dict[str, dict] = {
            "github:1": {
                "repo": "owner/alpha",
                "stars": 1,
                "description": "",
                "avatarUrl": "",
                "name": "Alpha old",
                "main": "main-old",
                "dev": "dev-old",
                "image": "image-old",
            }
        }
        self.patch_context.enter_context(
            patch.object(
                bundle_fetch,
                "fetch_repo_details",
                side_effect=lambda url: {
                    "id": "github:1" if url.endswith("owner/alpha") else "github:2",
                    "full_name": "owner/alpha",
                    "stars": 1,
                },
            )
        )
        self.discovery_path = self.root / "discovery.json"
        save_json(self.repos_path, self.initial_repos)
        save_json(self.discovery_path, {"providers": {}, "repositories": {"https://github.com/owner/alpha": {}}})
        self.bundle_data = {"download_url": "https://github.com/owner/alpha/releases/download/latest/bundle.mpp"}
        self.patches_data = {"patches": [{"name": "Valid patch"}]}
        mpp_buffer = io.BytesIO()
        with zipfile.ZipFile(mpp_buffer, "w") as archive:
            archive.writestr("META-INF/MANIFEST.MF", "Name: Alpha new\n")
        self.mpp_bytes = mpp_buffer.getvalue()
        self.responses: dict[str, bytes | Exception] = {self.bundle_data["download_url"]: self.mpp_bytes}
        for branch in DEFAULT_BRANCHES:
            self.responses[self.url(branch, "patches-bundle.json")] = json.dumps(self.bundle_data).encode()
            self.responses[self.url(branch, "patches-list.json")] = json.dumps(self.patches_data).encode()
        self.patch_context.enter_context(
            patch.multiple(
                bundle_fetch,
                BUNDLE_PARSER_DIR=self.parser_dir,
                BUNDLES_DIR=self.bundles_dir,
                PATCHES_DIR=self.patches_dir,
                MPP_DIR=self.mpp_dir,
                REPOS_JSON_PATH=self.repos_path,
                DISCOVERY_JSON_PATH=self.discovery_path,
                UPDATED_FILES_PATH=self.updated_path,
                PARSED_FILES_PATH=self.parsed_path,
                DEFAULT_BRANCHES=("main",),
            )
        )
        self.fetch_request = self.patch_context.enter_context(
            patch.object(bundle_fetch, "request", side_effect=self.download)
        )
        self.fetch_hash = self.patch_context.enter_context(
            patch.object(bundle_fetch, "get_remote_file_hash", return_value="main-new")
        )
        self.github_metadata_request = self.patch_context.enter_context(
            patch.object(bundle_fetch, "get_github_bundle", side_effect=self.github_metadata)
        )
        self.summary = self.patch_context.enter_context(patch.object(bundle_fetch, "append_step_summary"))
        self.run_process = self.patch_context.enter_context(patch.object(bundle_fetch.subprocess, "run"))

    def save_repos(self, repositories: dict) -> None:
        save_json(self.repos_path, repositories)

    def url(self, branch: str, filename: str) -> str:
        url = build_raw_url("github", "owner/alpha", branch, filename)
        assert url is not None
        return url

    def download(self, url: str) -> httpx2.Response:
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return httpx2.Response(200, content=response)

    def github_metadata(self, url: str, current_sha: str | None) -> tuple[str, bytes | None]:
        remote_sha = self.fetch_hash(url, "github")
        if current_sha and remote_sha == current_sha:
            return (current_sha, None)
        return (remote_sha, self.fetch_request(url).content)

    def seed_target(self) -> dict[Path, bytes]:
        old_contents = {
            self.bundles_dir / "github-1-main.json": b'{"version": "old"}',
            self.patches_dir / "github-1-main.json": b'{"patches": [{"name": "Old patch"}]}',
            self.mpp_dir / "github-1-main.mpp": b"old mpp",
        }
        for path, content in old_contents.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        return old_contents

    def test_patch_lists_download_concurrently_and_keep_targets_separate(self) -> None:
        barrier = threading.Barrier(len(DEFAULT_BRANCHES))
        patch_urls = {self.url(branch, "patches-list.json") for branch in DEFAULT_BRANCHES}

        def download(url: str) -> httpx2.Response:
            if url in patch_urls:
                assert threading.current_thread() is not threading.main_thread()
                barrier.wait(timeout=PATCH_LIST_BARRIER_TIMEOUT_SECONDS)
            return self.download(url)

        self.fetch_request.side_effect = download
        self.fetch_hash.side_effect = lambda url, _source: "dev-new" if "/dev/" in url else "main-new"
        self.updated_path.write_text("mpp/stale.mpp", encoding="utf-8")
        with patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES):
            bundle_fetch.fetch_all_repos()
        for branch in DEFAULT_BRANCHES:
            file_prefix = f"github-1-{branch}"
            assert load_json(self.bundles_dir / f"{file_prefix}.json") == self.bundle_data
            assert load_json(self.patches_dir / f"{file_prefix}.json") == self.patches_data
            assert (self.mpp_dir / f"{file_prefix}.mpp").read_bytes() == self.mpp_bytes
        updated_repo = load_json(self.repos_path)["github:1"]
        assert updated_repo["name"] == "Alpha new"
        for branch in DEFAULT_BRANCHES:
            assert updated_repo[branch] == f"{branch}-new"
        assert not self.updated_path.exists()
        self.run_process.assert_not_called()
        assert self.fetch_request.call_args_list.count(call(self.bundle_data["download_url"])) == 1

    def test_different_bundle_urls_are_downloaded_separately(self) -> None:
        dev_bundle_data = {"download_url": "https://github.com/owner/alpha/releases/download/dev/bundle.mpp"}
        self.responses[self.url("dev", "patches-bundle.json")] = json.dumps(dev_bundle_data).encode()
        self.responses[dev_bundle_data["download_url"]] = self.mpp_bytes
        with patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES):
            bundle_fetch.fetch_all_repos()
        for url in (self.bundle_data["download_url"], dev_bundle_data["download_url"]):
            assert self.fetch_request.call_args_list.count(call(url)) == 1
        for branch in DEFAULT_BRANCHES:
            assert (self.mpp_dir / f"github-1-{branch}.mpp").read_bytes() == self.mpp_bytes

    def test_bundle_downloads_are_not_reused_between_fetch_runs(self) -> None:
        bundle_fetch.fetch_all_repos()
        self.save_repos(self.initial_repos)
        bundle_fetch.fetch_all_repos()
        assert self.fetch_request.call_args_list.count(call(self.bundle_data["download_url"])) == 2

    def test_only_patch_list_404_queues_downloaded_mpp(self) -> None:
        url = self.url("main", "patches-list.json")
        self.responses[url] = self.http_error(url, HTTP_NOT_FOUND)
        result = bundle_fetch.process_repo_branch("github", "owner/alpha", "main", "main-old", repo_id="github:1")
        assert result.needs_parse
        assert result.new_sha == "main-new"
        assert (self.mpp_dir / f"{result.target_name}.mpp").read_bytes() == self.mpp_bytes
        self.run_process.assert_not_called()

    def test_unchanged_target_skips_downloads_without_local_mpp(self) -> None:
        save_json(self.bundles_dir / "github-1-main.json", self.bundle_data)
        save_json(self.patches_dir / "github-1-main.json", self.patches_data)
        self.fetch_hash.return_value = "main-old"
        original_content = self.repos_path.read_bytes()
        bundle_fetch.fetch_all_repos()
        self.fetch_request.assert_not_called()
        self.run_process.assert_not_called()
        assert self.repos_path.read_bytes() == original_content
        self.github_metadata_request.assert_called_once_with(self.url("main", "patches-bundle.json"), "main-old")

    @pytest.mark.parametrize("directory_name", ("bundles", "patches"))
    def test_missing_json_refetches_even_with_unchanged_hash(self, directory_name) -> None:
        self.fetch_hash.return_value = "main-old"
        missing_directory = {"bundles": self.bundles_dir, "patches": self.patches_dir}[directory_name]
        self.seed_target()
        (missing_directory / "github-1-main.json").unlink()
        self.fetch_request.reset_mock()
        self.github_metadata_request.reset_mock()
        bundle_fetch.fetch_all_repos()
        assert load_json(self.patches_dir / "github-1-main.json") == self.patches_data
        assert self.fetch_request.call_count == 3
        self.github_metadata_request.assert_called_once_with(self.url("main", "patches-bundle.json"), None)

    def test_null_sha_refetches_despite_existing_local_files(self) -> None:
        self.seed_target()
        result = bundle_fetch.process_repo_branch("github", "owner/alpha", "main", None, repo_id="github:1")
        self.github_metadata_request.assert_called_once_with(self.url("main", "patches-bundle.json"), None)
        assert result.new_sha == "main-new"
        assert result.status_changed

    def test_metadata_200_skips_download_when_etag_matches_saved_sha(self) -> None:
        self.seed_target()
        self.github_metadata_request.side_effect = None
        self.github_metadata_request.return_value = (
            "main-old",
            json.dumps(self.bundle_data).encode(),
        )
        result = bundle_fetch.process_repo_branch("github", "owner/alpha", "main", "main-old", repo_id="github:1")
        assert not result.status_changed
        assert result.new_sha == "main-old"
        self.fetch_request.assert_not_called()

    def test_gitlab_unchanged_metadata_still_skips_get(self) -> None:
        self.fetch_hash.return_value = "main-old"
        for directory in (self.bundles_dir, self.patches_dir):
            save_json(directory / "gitlab-1-main.json", {})
        result = bundle_fetch.process_repo_branch("gitlab", "owner/alpha", "main", "main-old", repo_id="gitlab:1")
        assert result.new_sha == "main-old"
        assert not result.status_changed
        self.fetch_hash.assert_called_once_with(
            build_raw_url("gitlab", "owner/alpha", "main", "patches-bundle.json"),
            "gitlab",
        )
        self.github_metadata_request.assert_not_called()
        self.fetch_request.assert_not_called()

    @pytest.mark.parametrize(
        "stage,failure_kind",
        (
            ("hash", "timeout"),
            ("metadata", 503),
            ("mpp", "network"),
            ("mpp", "invalid-url"),
            ("patches", 451),
        ),
    )
    def test_request_failure_preserves_saved_target(self, stage, failure_kind) -> None:
        urls = {
            "metadata": self.url("main", "patches-bundle.json"),
            "mpp": self.bundle_data["download_url"],
            "patches": self.url("main", "patches-list.json"),
        }
        if failure_kind == "timeout":
            failure = TimeoutError("Timed out")
        elif failure_kind == "network":
            failure = httpx2.ConnectError("DNS failure")
        elif failure_kind == "invalid-url":
            failure = httpx2.InvalidURL("Invalid download URL")
        else:
            failure = self.http_error(urls[stage], failure_kind)
        if stage == "hash":
            self.fetch_hash.side_effect = failure
        else:
            self.responses[urls[stage]] = failure
        old_contents = self.seed_target()
        bundle_fetch.fetch_all_repos()
        assert load_json(self.repos_path) == self.initial_repos
        for path, content in old_contents.items():
            assert path.read_bytes() == content
        self.run_process.assert_not_called()

    def test_missing_metadata_is_grouped_by_source_and_repository(self) -> None:
        results = [
            bundle_fetch.BranchFetchResult(
                source,
                repo,
                branch,
                None,
                error_category="metadata",
                error_message="HTTP Error 404: Request failed",
                repo_id=source + ":1",
            )
            for source, repo, branch in (
                ("github", "owner/alpha", "main"),
                ("gitlab", "owner/alpha", "dev"),
                ("github", "owner/beta", "dev"),
            )
        ]
        with patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES):
            assert not any(bundle_fetch.collect_fetch_errors(results).values())
            results.append(
                bundle_fetch.BranchFetchResult(
                    "gitlab",
                    "owner/alpha",
                    "main",
                    None,
                    error_category="metadata",
                    error_message="HTTP Error 404: Request failed",
                    repo_id="gitlab:1",
                )
            )
            errors = bundle_fetch.collect_fetch_errors(results)
        assert len(errors["metadata"]) == 1
        assert "https://gitlab.com/owner/alpha" in errors["metadata"][0]
        assert "404" in errors["metadata"][0]
        assert sum(len(messages) for messages in errors.values()) == 1

    @pytest.mark.parametrize(
        "categories,expected_counts",
        (
            (("bundle", "bundle"), {"bundle": 1}),
            (("metadata", "bundle"), {"metadata": 1, "bundle": 1}),
        ),
    )
    def test_errors_are_deduplicated_per_repository_and_stage(self, categories, expected_counts) -> None:
        results = [
            bundle_fetch.BranchFetchResult(
                "github",
                "owner/alpha",
                branch,
                None,
                error_category=category,
                error_message="HTTP 503",
                repo_id="github:1",
            )
            for branch, category in zip(DEFAULT_BRANCHES, categories, strict=True)
        ]
        with patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES):
            errors = bundle_fetch.collect_fetch_errors(results)
        assert {category: len(messages) for category, messages in errors.items() if messages} == expected_counts
        assert all("https://github.com/owner/alpha" in message for messages in errors.values() for message in messages)

    @pytest.mark.parametrize("category", ("metadata", "bundle", "patch_list"))
    def test_branch_errors_are_suppressed_when_the_other_branch_succeeds(self, category) -> None:
        results = [
            bundle_fetch.BranchFetchResult(
                "github",
                "owner/alpha",
                "main",
                "main-old",
                error_category=category,
                error_message="HTTP Error 503: Request failed",
                repo_id="github:1",
            ),
            bundle_fetch.BranchFetchResult("github", "owner/alpha", "dev", "dev-new", repo_id="github:1"),
        ]
        with patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES):
            assert not any(bundle_fetch.collect_fetch_errors(results).values())

    @pytest.mark.parametrize("code", (403, 451))
    def test_patch_list_request_errors_do_not_trigger_parsing(self, code) -> None:
        for branch in DEFAULT_BRANCHES:
            url = self.url(branch, "patches-list.json")
            self.responses[url] = self.http_error(url, code)
        with patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES):
            bundle_fetch.fetch_all_repos()
        self.run_process.assert_not_called()
        assert load_json(self.repos_path) == self.initial_repos

    def test_failed_parser_batch_does_not_confirm_branches(
        self,
    ) -> None:
        for branch in DEFAULT_BRANCHES:
            url = self.url(branch, "patches-list.json")
            self.responses[url] = self.http_error(url, HTTP_NOT_FOUND)

        def run_parser(*_args: object, **_kwargs: object) -> None:
            self.parsed_path.write_text("", encoding="utf-8")

        self.run_process.side_effect = run_parser
        with patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES):
            bundle_fetch.fetch_all_repos()
        self.run_process.assert_called_once()
        for branch in DEFAULT_BRANCHES:
            assert load_json(self.repos_path)["github:1"][branch] is None

    @pytest.mark.parametrize("stage,code", (("hash", 404), ("metadata", 451), ("mpp", 404)))
    def test_unavailable_metadata_and_mpp_clear_sha_without_deleting_files(self, stage, code) -> None:
        original_responses = self.responses.copy()
        self.save_repos(self.initial_repos)
        self.responses = original_responses.copy()
        self.fetch_hash.side_effect = (
            self.http_error(self.url("main", "patches-bundle.json"), code) if stage == "hash" else None
        )
        if stage != "hash":
            url = self.url("main", "patches-bundle.json") if stage == "metadata" else self.bundle_data["download_url"]
            self.responses[url] = self.http_error(url, code)
        old_contents = self.seed_target()
        bundle_fetch.fetch_all_repos()
        assert load_json(self.repos_path)["github:1"]["main"] is None
        for path, content in old_contents.items():
            assert path.read_bytes() == content
        self.run_process.assert_not_called()

    @pytest.mark.parametrize(
        "content",
        [
            b"{broken",
            b"{}",
            json.dumps({"download_url": "https://github.com/other/repo/bundle.mpp"}).encode(),
            *(
                json.dumps({"download_url": url}).encode()
                for url in (
                    "http://github.com/owner/alpha/bundle.mpp",
                    "https://github.com.evil.example/owner/alpha/bundle.mpp",
                )
            ),
        ],
    )
    def test_invalid_metadata_clears_target(self, content) -> None:
        self.responses[self.url("main", "patches-bundle.json")] = content
        with patch.object(
            bundle_fetch,
            "fetch_repo_details",
            side_effect=lambda url: {"id": "github:2", "full_name": parse_repo_url(url)[1]},
        ):
            result = bundle_fetch.process_repo_branch("github", "owner/alpha", "main", "main-old", repo_id="github:1")
        assert result.new_sha is None
        assert not result.needs_parse
        assert result.error_message
        assert result.error_category == "metadata"
        assert result.error_message in ("Invalid data", "Invalid `download_url`")

    def test_unreadable_manifest_keeps_existing_display_name(self) -> None:
        self.responses[self.bundle_data["download_url"]] = b"not a zip archive"
        bundle_fetch.fetch_all_repos()
        updated_repo = load_json(self.repos_path)["github:1"]
        assert updated_repo["name"] == "Alpha old"
        assert updated_repo["main"] == "main-new"

    @pytest.mark.parametrize("source", ("github", "gitlab"))
    @pytest.mark.parametrize("same_id", (True, False))
    def test_download_under_old_name_must_resolve_to_same_id(self, source, same_id) -> None:
        download_url = f"https://{source}.com/owner/old/releases/download/latest/bundle.mpp"
        manifest_url = build_raw_url(source, "owner/alpha", "main", "patches-bundle.json")
        patch_url = build_raw_url(source, "owner/alpha", "main", "patches-list.json")
        assert manifest_url is not None and patch_url is not None
        self.responses[manifest_url] = json.dumps({"download_url": download_url}).encode()
        self.responses[download_url] = self.mpp_bytes
        self.responses[patch_url] = json.dumps(self.patches_data).encode()
        with patch.object(
            bundle_fetch,
            "fetch_repo_details",
            return_value={"id": f"{source}:{1 if same_id else 2}", "full_name": "owner/alpha"},
        ):
            result = bundle_fetch.process_repo_branch(source, "owner/alpha", "main", "main-old", f"{source}:1")
        assert result.new_sha == ("main-new" if same_id else None)
        assert bool(result.error_message) != same_id
        assert (call(download_url) in self.fetch_request.call_args_list) == same_id

    @pytest.mark.parametrize("project_id", (1, 2))
    def test_gitlab_numeric_download_project_must_match_repository_id(self, project_id) -> None:
        download_url = f"https://gitlab.com/api/v4/projects/{project_id}/packages/generic/patches/1/bundle.mpp"
        manifest_url = build_raw_url("gitlab", "owner/alpha", "main", "patches-bundle.json")
        patch_url = build_raw_url("gitlab", "owner/alpha", "main", "patches-list.json")
        assert manifest_url is not None and patch_url is not None
        self.responses[manifest_url] = json.dumps({"download_url": download_url}).encode()
        self.responses[download_url] = self.mpp_bytes
        self.responses[patch_url] = json.dumps(self.patches_data).encode()
        result = bundle_fetch.process_repo_branch("gitlab", "owner/alpha", "main", "main-old", "gitlab:1")
        assert result.new_sha == ("main-new" if project_id == 1 else None)
        assert (call(download_url) in self.fetch_request.call_args_list) == (project_id == 1)

    def test_daily_unavailable_mpp_clears_sha_and_retains_files(self) -> None:
        save_json(self.bundles_dir / "github-1-main.json", self.bundle_data)
        save_json(self.patches_dir / "github-1-main.json", self.patches_data)
        self.fetch_hash.return_value = "main-old"
        with patch.object(
            bundle_fetch,
            "get_remote_file_hash",
            side_effect=[
                self.http_error(self.bundle_data["download_url"], HTTP_NOT_FOUND),
                "image-old",
            ],
        ):
            bundle_fetch.fetch_all_repos(daily=True)
        assert load_json(self.repos_path)["github:1"]["main"] is None
        assert (self.patches_dir / "github-1-main.json").exists()
        self.fetch_request.assert_not_called()

    def test_daily_check_failure_preserves_sha(self) -> None:
        save_json(self.bundles_dir / "github-1-main.json", self.bundle_data)
        save_json(self.patches_dir / "github-1-main.json", self.patches_data)
        self.fetch_hash.return_value = "main-old"
        with patch.object(
            bundle_fetch,
            "get_remote_file_hash",
            side_effect=TimeoutError("Check failed"),
        ):
            result = bundle_fetch.process_repo_branch(
                "github", "owner/alpha", "main", "main-old", daily=True, repo_id="github:1"
            )
        assert result.new_sha == "main-old"
        assert not result.status_changed
        self.fetch_request.assert_not_called()

    def test_image_updates_are_independent_of_branch_failures(self) -> None:
        self.fetch_hash.side_effect = [
            self.http_error(self.url("main", "patches-bundle.json"), HTTP_NOT_FOUND),
            "image-new",
        ]
        bundle_fetch.fetch_all_repos(daily=True)
        updated_repo = load_json(self.repos_path)["github:1"]
        assert updated_repo["image"] == "image-new"
        assert updated_repo["main"] is None
        assert updated_repo["name"] == "Alpha old"

    def test_file_write_failure_stops_fetch(self) -> None:
        with (
            patch.object(bundle_fetch, "save_json", side_effect=PermissionError("Cannot write")),
            pytest.raises(PermissionError),
        ):
            bundle_fetch.fetch_all_repos()
        assert load_json(self.repos_path) == self.initial_repos

    def test_parser_failure_stops_before_saving_repos(self) -> None:
        patch_url = self.url("main", "patches-list.json")
        self.responses[patch_url] = self.http_error(patch_url, HTTP_NOT_FOUND)
        self.run_process.side_effect = OSError("Cannot launch parser")
        with pytest.raises(OSError):
            bundle_fetch.fetch_all_repos()
        assert load_json(self.repos_path) == self.initial_repos

    def test_partial_parser_batch_publishes_only_successful_target(self) -> None:
        for branch in DEFAULT_BRANCHES:
            patch_url = self.url(branch, "patches-list.json")
            self.responses[patch_url] = self.http_error(patch_url, HTTP_NOT_FOUND)
        self.fetch_hash.side_effect = lambda url, _source: "dev-new" if "/dev/" in url else "main-new"
        save_json(self.patches_dir / "github-1-dev.json", self.patches_data)

        def run_parser(*_args: object, **_kwargs: object) -> bundle_fetch.subprocess.CompletedProcess:
            assert not self.parsed_path.exists()
            save_json(self.patches_dir / "github-1-main.json", self.patches_data)
            self.parsed_path.write_text("github-1-main.json", encoding="utf-8")
            return bundle_fetch.subprocess.CompletedProcess([], 0)

        self.run_process.side_effect = run_parser
        with (
            patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES),
        ):
            bundle_fetch.fetch_all_repos()
        updated_repo = load_json(self.repos_path)["github:1"]
        assert updated_repo["main"] == "main-new"
        assert updated_repo["dev"] is None
        assert updated_repo["name"] == "Alpha new"
        self.run_process.assert_called_once()

    def test_main_name_wins_independently_of_worker_completion_order(self) -> None:

        def process(
            source: str, repo: str, branch: str, _sha: str | None, repo_id: str, **_kwargs: object
        ) -> bundle_fetch.BranchFetchResult:
            return bundle_fetch.BranchFetchResult(
                source, repo, branch, "new", status_changed=True, bundle_name=f"{branch} name", repo_id=source + ":1"
            )

        with (
            patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES),
            patch.object(bundle_fetch, "process_repo_branch", side_effect=process),
        ):
            bundle_fetch.fetch_all_repos()
        assert load_json(self.repos_path)["github:1"]["name"] == "main name"

    def test_dev_update_downloads_bundle_but_keeps_existing_main_name(self) -> None:
        self.seed_target()
        save_json(self.bundles_dir / "github-1-main.json", self.bundle_data)
        self.fetch_hash.side_effect = lambda url, _source: "main-old" if "/main/" in url else "dev-new"
        with patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES):
            bundle_fetch.fetch_all_repos()
        assert load_json(self.repos_path)["github:1"]["name"] == "Alpha old"
        self.fetch_request.assert_any_call(self.url("dev", "patches-list.json"))
        assert (self.mpp_dir / "github-1-dev.mpp").is_file()

    def test_new_empty_repository_entry_is_fetched(self) -> None:
        self.save_repos({})
        bundle_fetch.fetch_all_repos()
        assert load_json(self.repos_path)["github:1"]["main"] == "main-new"
        assert load_json(self.repos_path)["github:1"]["name"] == "Alpha new"
        assert load_json(self.discovery_path)["repositories"]["https://github.com/owner/alpha"]["id"] == "github:1"


class TestRepositoryMetadataRefresh:
    @pytest.mark.parametrize("config", ({}, {"revancedStars": 5}, {"enabled": False, "revancedStars": 5}))
    def test_aliases_merge_by_id_and_later_config_replaces_previous(self, config) -> None:
        old_url = "https://github.com/owner/old"
        new_url = "https://github.com/owner/new"
        existing = {
            "github:1": {
                "repo": "owner/old",
                "main": "saved",
                "enabled": False,
                "revancedStars": 99,
                "isArchived": True,
            }
        }
        discovered = {new_url: {"revancedStars": 99}, old_url: dict(config)}
        with patch.object(
            bundle_fetch, "fetch_repo_details", return_value={"id": "github:1", "full_name": "Owner/New", "stars": 10}
        ) as lookup:
            actual, warnings, failed = bundle_fetch.refresh_repo_metadata(
                discovered, existing, bundle_fetch.RepositoryDetails()
            )
        assert lookup.call_count == 2
        assert set(actual) == {"github:1"}
        assert actual["github:1"]["repo"] == "Owner/New"
        assert actual["github:1"]["main"] == "saved"
        assert discovered[old_url]["id"] == discovered[new_url]["id"] == "github:1"
        assert {
            field: actual["github:1"][field] for field in ("enabled", "revancedStars") if field in actual["github:1"]
        } == config
        assert "isArchived" not in actual["github:1"]
        assert not failed
        assert not warnings

    def test_disabled_identity_skips_known_urls_and_tracks_unknown_aliases(self) -> None:
        old_url = "https://github.com/owner/old"
        new_url = "https://github.com/owner/new"
        existing = {
            "github:1": {"repo": "owner/old", "main": "saved"},
            "github:3": {"repo": "owner/removed"},
        }
        details = {
            old_url: {"id": "github:2", "full_name": "owner/old"},
            new_url: {"id": "github:1", "full_name": "owner/new", "is_archived": True},
        }
        discovered = {old_url: {"id": "github:1", "enabled": False}, new_url: {}}
        with patch.object(bundle_fetch, "fetch_repo_details", side_effect=details.__getitem__) as lookup:
            actual, warnings, failed = bundle_fetch.refresh_repo_metadata(
                discovered, existing, bundle_fetch.RepositoryDetails()
            )
        lookup.assert_called_once_with(new_url)
        assert set(actual) == {"github:1"}
        assert actual["github:1"]["main"] == "saved"
        assert actual["github:1"]["enabled"] is False
        assert discovered[old_url]["id"] == discovered[new_url]["id"] == "github:1"
        assert not warnings
        assert not failed

        with patch.object(bundle_fetch, "fetch_repo_details") as lookup:
            repeated, warnings, failed = bundle_fetch.refresh_repo_metadata(
                discovered, actual, bundle_fetch.RepositoryDetails()
            )
        lookup.assert_not_called()
        assert repeated == actual
        assert not warnings
        assert not failed

        discovered[old_url].pop("enabled")
        with patch.object(bundle_fetch, "fetch_repo_details", side_effect=details.__getitem__) as lookup:
            enabled, _warnings, failed = bundle_fetch.refresh_repo_metadata(
                discovered, repeated, bundle_fetch.RepositoryDetails()
            )
        assert lookup.call_count == 2
        assert set(enabled) == {"github:1", "github:2"}
        assert enabled["github:1"]["main"] == "saved"
        assert all("enabled" not in metadata for metadata in enabled.values())
        assert "main" not in enabled["github:2"]
        assert discovered[old_url]["id"] == "github:2"
        assert not failed

    @pytest.mark.parametrize(
        "error,alias_error,expected_sha",
        (
            ({"error": "timed out"}, {"error": "timed out"}, "saved"),
            ({"error": "HTTP 404", "is_404": True}, {"error": "HTTP 404", "is_404": True}, None),
            ({"error": "HTTP 451", "is_451": True}, {"error": "HTTP 451", "is_451": True}, None),
            ({"error": "HTTP 404", "is_404": True}, {"error": "timed out"}, None),
        ),
    )
    def test_metadata_failure_preserves_identity_and_only_clears_unavailable_hash(
        self, error, alias_error, expected_sha
    ) -> None:
        url = "https://github.com/owner/old"
        alias_url = "https://github.com/owner/new"
        unknown_url = "https://github.com/owner/unknown"
        existing = {"github:1": {"repo": "owner/new", "main": "saved"}, "github:2": {"repo": "owner/removed"}}
        responses = {url: error, alias_url: alias_error, unknown_url: error}
        with patch.object(bundle_fetch, "fetch_repo_details", side_effect=responses.__getitem__):
            actual, warnings, failed = bundle_fetch.refresh_repo_metadata(
                {url: {"id": "github:1"}, alias_url: {"id": "github:1"}, unknown_url: {}},
                existing,
                bundle_fetch.RepositoryDetails(),
            )
        assert actual["github:1"]["repo"] == "owner/new"
        assert actual["github:1"]["main"] == expected_sha
        assert failed == {"github:1"}
        assert set(actual) == {"github:1"}
        assert warnings == [(url, error["error"]), (alias_url, alias_error["error"]), (unknown_url, error["error"])]

    def test_disabled_repositories_resolve_once_and_skip_bundle_and_summary(self, tmp_path: Path) -> None:
        url = "https://github.com/owner/disabled"
        discovery_path = tmp_path / "discovery.json"
        repos_path = tmp_path / "repos.json"
        save_json(discovery_path, {"providers": {}, "repositories": {url: {"enabled": False}}})
        with (
            patch.multiple(
                bundle_fetch,
                DISCOVERY_JSON_PATH=discovery_path,
                REPOS_JSON_PATH=repos_path,
                BUNDLES_DIR=tmp_path / "bundles",
                PATCHES_DIR=tmp_path / "patches",
                MPP_DIR=tmp_path / "mpp",
            ),
            patch.object(
                bundle_fetch,
                "fetch_repo_details",
                return_value={"id": "github:1", "full_name": "owner/new", "stars": 8},
            ) as metadata,
            patch.object(bundle_fetch, "process_repo_branch", side_effect=AssertionError("Disabled bundle")) as branch,
            patch.object(bundle_fetch, "run_bundle_parser"),
            patch.object(bundle_fetch, "process_image", side_effect=AssertionError("Disabled image")) as image,
            patch.object(bundle_fetch, "append_step_summary") as summary,
        ):
            bundle_fetch.fetch_all_repos(True)
            bundle_fetch.fetch_all_repos(True)
        metadata.assert_called_once_with(url)
        branch.assert_not_called()
        image.assert_not_called()
        assert load_json(repos_path)["github:1"]["enabled"] is False
        assert summary.call_args.args[0] == "## 📥 Fetch (0/0):"
