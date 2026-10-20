import io
import json
import threading
import urllib.error
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, call, patch

import pytest

import fetch as bundle_fetch
from common.utils import DEFAULT_BRANCHES, build_raw_url, load_json, save_json

PATCH_LIST_BARRIER_TIMEOUT_SECONDS = 5
DOWNLOAD_WAIT_TIMEOUT_SECONDS = 5
HTTP_NOT_FOUND = 404
HTTP_UNAVAILABLE_CODES = (404, 451)
HTTP_OTHER_CODES = (403, 429, 500, 503)


class TestGithubBundle:
    @pytest.fixture(autouse=True)
    def prepare(self, patch_context) -> None:
        self.patch_context = patch_context
        self.url = build_raw_url("github", "owner/alpha", "main", "patches-bundle.json")
        self.open_url = self.patch_context.enter_context(
            patch.object(bundle_fetch.urllib.request, "urlopen")
        )
        self.response = self.open_url.return_value.__enter__.return_value
        self.response.getheader.return_value = '"new-hash"'
        self.response.read.return_value = b'{"download_url": "bundle.mpp"}'

    def test_changed_metadata_uses_one_conditional_get_with_response_etag(self) -> None:
        result = bundle_fetch.get_github_bundle(self.url, "old-hash")
        assert result == ("new-hash", self.response.read.return_value)
        self.open_url.assert_called_once()
        request = self.open_url.call_args.args[0]
        assert request.get_method() == "GET"
        assert request.get_header("If-none-match") == '"old-hash"'
        self.response.read.assert_called_once()

    def test_unconfirmed_metadata_uses_unconditional_get(self) -> None:
        bundle_fetch.get_github_bundle(self.url, None)
        assert self.open_url.call_args.args[0].get_header("If-none-match") is None
        self.response.read.assert_called_once()

    def test_not_modified_preserves_hash_without_reading_body(self) -> None:
        body = io.BytesIO()
        self.open_url.side_effect = urllib.error.HTTPError(
            self.url, 304, "Not Modified", None, body
        )
        assert bundle_fetch.get_github_bundle(self.url, "old-hash") == (
            "old-hash",
            None,
        )
        self.open_url.assert_called_once()
        self.response.read.assert_not_called()
        assert body.closed

    @pytest.mark.parametrize("code", (304, *HTTP_UNAVAILABLE_CODES, *HTTP_OTHER_CODES))
    def test_http_errors_propagate_with_actual_status(self, code) -> None:
        error = urllib.error.HTTPError(self.url, code, "Request failed", None, None)
        self.patch_context.callback(error.close)
        self.open_url.side_effect = error
        with pytest.raises(urllib.error.HTTPError) as raised:
            bundle_fetch.get_github_bundle(self.url, None)
        assert raised.value is error

    def test_network_errors_propagate_without_retry(self) -> None:
        error = urllib.error.URLError("DNS failure")
        self.open_url.side_effect = error
        with pytest.raises(urllib.error.URLError) as raised:
            bundle_fetch.get_github_bundle(self.url, "old-hash")
        assert raised.value is error
        self.open_url.assert_called_once()

    def test_missing_etag_is_reported_before_reading_body(self) -> None:
        self.response.getheader.return_value = None
        with pytest.raises(ValueError, match="Missing `ETag`"):
            bundle_fetch.get_github_bundle(self.url, None)
        self.response.read.assert_not_called()


def test_concurrent_targets_share_download_without_blocking_other_urls() -> None:
    shared_url = "https://example.com/shared.mpp"
    other_url = "https://example.com/other.mpp"
    download_started = threading.Event()
    release_download = threading.Event()
    downloads = bundle_fetch.BundleDownloads()

    def download(url: str, *, binary: bool) -> bytes:
        assert binary
        if url == shared_url:
            download_started.set()
            assert release_download.wait(timeout=DOWNLOAD_WAIT_TIMEOUT_SECONDS)
        return url.encode()

    with (
        patch.object(bundle_fetch, "fetch", side_effect=download) as request,
        ThreadPoolExecutor(max_workers=3) as executor,
    ):
        first = executor.submit(downloads.download, shared_url)
        try:
            assert download_started.wait(timeout=DOWNLOAD_WAIT_TIMEOUT_SECONDS)
            second = executor.submit(downloads.download, shared_url)
            other = executor.submit(downloads.download, other_url)
            assert (
                other.result(timeout=DOWNLOAD_WAIT_TIMEOUT_SECONDS)
                == other_url.encode()
            )
        finally:
            release_download.set()
        assert first.result() == shared_url.encode()
        assert second.result() == shared_url.encode()
    assert request.call_count == 2


class TestBundleFetch:
    @pytest.fixture(autouse=True)
    def prepare(self, tmp_path: Path, patch_context) -> None:
        self.patch_context = patch_context
        self.root = tmp_path
        self.parser_dir = self.root / "bundle-parser"
        self.parser_dir.mkdir()
        self.bundles_dir = self.root / "bundles"
        self.patches_dir = self.root / "patches"
        self.mpp_dir = self.parser_dir / "mpp"
        self.repos_path = self.root / "repos.json"
        self.updated_path = self.parser_dir / "updated_files.txt"
        self.parsed_path = self.parser_dir / "parsed_files.txt"
        self.initial_repos = {
            "https://github.com/owner/alpha": {
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
                return_value={"error": "Request failed (HTTP 503)"},
            )
        )
        self.patch_context.enter_context(
            patch.object(bundle_fetch, "refresh_repo_metadata", return_value=[])
        )
        save_json(self.repos_path, self.initial_repos)
        self.bundle_data = {
            "download_url": "https://github.com/owner/alpha/releases/download/latest/bundle.mpp"
        }
        self.patches_data = {"patches": [{"name": "Valid patch"}]}
        mpp_buffer = io.BytesIO()
        with zipfile.ZipFile(mpp_buffer, "w") as archive:
            archive.writestr("META-INF/MANIFEST.MF", "Name: Alpha new\n")
        self.mpp_bytes = mpp_buffer.getvalue()
        self.responses = {self.bundle_data["download_url"]: self.mpp_bytes}
        for branch in DEFAULT_BRANCHES:
            self.responses[self.url(branch, "patches-bundle.json")] = json.dumps(
                self.bundle_data
            ).encode()
            self.responses[self.url(branch, "patches-list.json")] = json.dumps(
                self.patches_data
            ).encode()
        self.patch_context.enter_context(
            patch.multiple(
                bundle_fetch,
                BUNDLE_PARSER_DIR=self.parser_dir,
                BUNDLES_DIR=self.bundles_dir,
                PATCHES_DIR=self.patches_dir,
                MPP_DIR=self.mpp_dir,
                REPOS_JSON_PATH=self.repos_path,
                UPDATED_FILES_PATH=self.updated_path,
                PARSED_FILES_PATH=self.parsed_path,
                DEFAULT_BRANCHES=("main",),
            )
        )
        self.fetch_request = self.patch_context.enter_context(
            patch.object(bundle_fetch, "fetch", side_effect=self.download)
        )
        self.fetch_hash = Mock(return_value="main-new")
        self.patch_context.enter_context(
            patch.object(bundle_fetch, "get_file_sha", side_effect=self.fetch_hash)
        )
        self.github_metadata_request = self.patch_context.enter_context(
            patch.object(
                bundle_fetch, "get_github_bundle", side_effect=self.github_metadata
            )
        )
        self.patch_context.enter_context(
            patch.object(bundle_fetch, "get_image_sha", return_value="image-old")
        )
        self.summary = self.patch_context.enter_context(
            patch.object(bundle_fetch, "append_step_summary")
        )
        self.run_process = self.patch_context.enter_context(
            patch.object(bundle_fetch.subprocess, "run")
        )

    def url(self, branch: str, filename: str) -> str:
        return build_raw_url("github", "owner/alpha", branch, filename)

    def download(self, url: str, binary: bool = False) -> str | bytes:
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response if binary else response.decode()

    def http_error(self, url: str, code: int) -> urllib.error.HTTPError:
        error = urllib.error.HTTPError(url, code, "Request failed", None, None)
        self.patch_context.callback(error.close)
        return error

    def github_metadata(
        self, url: str, current_sha: str | None
    ) -> tuple[str, bytes | None]:
        branch = next(
            branch
            for branch in DEFAULT_BRANCHES
            if url == self.url(branch, "patches-bundle.json")
        )
        remote_sha = self.fetch_hash("github", "owner/alpha", branch)
        if current_sha and remote_sha == current_sha:
            return (current_sha, None)
        return (remote_sha, self.fetch_request(url, binary=True))

    def seed_target(self) -> dict[Path, bytes]:
        old_contents = {
            self.bundles_dir / "github~owner~alpha~main.json": b'{"version": "old"}',
            self.patches_dir
            / "github~owner~alpha~main.json": b'{"patches": [{"name": "Old patch"}]}',
            self.mpp_dir / "github~owner~alpha~main.mpp": b"old mpp",
        }
        for path, content in old_contents.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        return old_contents

    def test_patch_lists_download_concurrently_and_keep_targets_separate(self) -> None:
        barrier = threading.Barrier(len(DEFAULT_BRANCHES))
        patch_urls = {
            self.url(branch, "patches-list.json") for branch in DEFAULT_BRANCHES
        }

        def download(url: str, binary: bool = False) -> str | bytes:
            if url in patch_urls:
                assert threading.current_thread() is not threading.main_thread()
                barrier.wait(timeout=PATCH_LIST_BARRIER_TIMEOUT_SECONDS)
            return self.download(url, binary=binary)

        self.fetch_request.side_effect = download
        self.fetch_hash.side_effect = lambda _source, _repo, branch: f"{branch}-new"
        self.updated_path.write_text("mpp/stale.mpp", encoding="utf-8")
        with patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES):
            bundle_fetch.fetch_all_repos()
        for branch in DEFAULT_BRANCHES:
            file_prefix = f"github~owner~alpha~{branch}"
            assert (
                load_json(self.bundles_dir / f"{file_prefix}.json") == self.bundle_data
            )
            assert (
                load_json(self.patches_dir / f"{file_prefix}.json") == self.patches_data
            )
            assert (self.mpp_dir / f"{file_prefix}.mpp").read_bytes() == self.mpp_bytes
        updated_repo = load_json(self.repos_path)["https://github.com/owner/alpha"]
        assert updated_repo["name"] == "Alpha new"
        for branch in DEFAULT_BRANCHES:
            assert updated_repo[branch] == f"{branch}-new"
        assert not self.updated_path.exists()
        self.run_process.assert_not_called()
        assert self.summary.call_args.args[0] == "## 📥 Fetch (1/1):"
        assert (
            self.fetch_request.call_args_list.count(
                call(self.bundle_data["download_url"], binary=True)
            )
            == 1
        )

    def test_different_bundle_urls_are_downloaded_separately(self) -> None:
        dev_bundle_data = {
            "download_url": "https://github.com/owner/alpha/releases/download/dev/bundle.mpp"
        }
        self.responses[self.url("dev", "patches-bundle.json")] = json.dumps(
            dev_bundle_data
        ).encode()
        self.responses[dev_bundle_data["download_url"]] = self.mpp_bytes
        with patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES):
            bundle_fetch.fetch_all_repos()
        for url in (self.bundle_data["download_url"], dev_bundle_data["download_url"]):
            assert self.fetch_request.call_args_list.count(call(url, binary=True)) == 1
        for branch in DEFAULT_BRANCHES:
            assert (
                self.mpp_dir / f"github~owner~alpha~{branch}.mpp"
            ).read_bytes() == self.mpp_bytes

    def test_bundle_downloads_are_not_reused_between_fetch_runs(self) -> None:
        bundle_fetch.fetch_all_repos()
        save_json(self.repos_path, self.initial_repos)
        bundle_fetch.fetch_all_repos()
        assert (
            self.fetch_request.call_args_list.count(
                call(self.bundle_data["download_url"], binary=True)
            )
            == 2
        )

    def test_only_patch_list_404_queues_downloaded_mpp(self) -> None:
        url = self.url("main", "patches-list.json")
        self.responses[url] = self.http_error(url, HTTP_NOT_FOUND)
        result = bundle_fetch.process_repo_branch(
            "github", "owner/alpha", "main", "main-old"
        )
        assert result.needs_parse
        assert result.new_sha == "main-new"
        assert (
            self.mpp_dir / f"{result.target_name}.mpp"
        ).read_bytes() == self.mpp_bytes
        self.run_process.assert_not_called()

    @pytest.mark.parametrize(
        "content", (b"{broken", b"{}", b'{"patches": []}', b"", b"\xff")
    )
    def test_downloaded_patch_list_is_saved_verbatim_without_validation(
        self, content
    ) -> None:
        save_json(self.repos_path, self.initial_repos)
        self.responses[self.url("main", "patches-list.json")] = content
        bundle_fetch.fetch_all_repos()
        assert (
            self.patches_dir / "github~owner~alpha~main.json"
        ).read_bytes() == content
        assert (
            load_json(self.repos_path)["https://github.com/owner/alpha"]["main"]
            == "main-new"
        )
        self.run_process.assert_not_called()

    def test_unchanged_target_skips_downloads_without_local_mpp(self) -> None:
        save_json(self.bundles_dir / "github~owner~alpha~main.json", self.bundle_data)
        save_json(self.patches_dir / "github~owner~alpha~main.json", self.patches_data)
        self.fetch_hash.return_value = "main-old"
        original_content = self.repos_path.read_bytes()
        bundle_fetch.fetch_all_repos()
        self.fetch_request.assert_not_called()
        self.run_process.assert_not_called()
        assert self.repos_path.read_bytes() == original_content
        assert self.summary.call_args.args[0] == "## 📥 Fetch (1/1):"
        self.github_metadata_request.assert_called_once_with(
            self.url("main", "patches-bundle.json"), "main-old"
        )

    @pytest.mark.parametrize("directory_name", ("bundles", "patches"))
    def test_missing_json_refetches_even_with_unchanged_hash(
        self, directory_name
    ) -> None:
        self.fetch_hash.return_value = "main-old"
        missing_directory = {"bundles": self.bundles_dir, "patches": self.patches_dir}[
            directory_name
        ]
        self.seed_target()
        (missing_directory / "github~owner~alpha~main.json").unlink()
        self.fetch_request.reset_mock()
        self.github_metadata_request.reset_mock()
        bundle_fetch.fetch_all_repos()
        assert (
            load_json(self.patches_dir / "github~owner~alpha~main.json")
            == self.patches_data
        )
        assert self.fetch_request.call_count == 3
        self.github_metadata_request.assert_called_once_with(
            self.url("main", "patches-bundle.json"), None
        )

    def test_null_sha_refetches_despite_existing_local_files(self) -> None:
        self.seed_target()
        result = bundle_fetch.process_repo_branch("github", "owner/alpha", "main", None)
        self.github_metadata_request.assert_called_once_with(
            self.url("main", "patches-bundle.json"), None
        )
        assert result.new_sha == "main-new"
        assert result.status_changed

    def test_metadata_200_is_processed_even_when_etag_matches_saved_sha(self) -> None:
        self.seed_target()
        self.github_metadata_request.side_effect = None
        self.github_metadata_request.return_value = (
            "main-old",
            json.dumps(self.bundle_data).encode(),
        )
        result = bundle_fetch.process_repo_branch(
            "github", "owner/alpha", "main", "main-old"
        )
        assert result.status_changed
        assert result.bundle_name == "Alpha new"
        assert (
            call(self.url("main", "patches-bundle.json"), binary=True)
            not in self.fetch_request.call_args_list
        )

    def test_gitlab_unchanged_metadata_still_skips_get(self) -> None:
        self.fetch_hash.return_value = "main-old"
        for directory in (self.bundles_dir, self.patches_dir):
            save_json(directory / "gitlab~owner~alpha~main.json", {})
        result = bundle_fetch.process_repo_branch(
            "gitlab", "owner/alpha", "main", "main-old"
        )
        assert result.new_sha == "main-old"
        assert not result.status_changed
        self.fetch_hash.assert_called_once_with("gitlab", "owner/alpha", "main")
        self.github_metadata_request.assert_not_called()
        self.fetch_request.assert_not_called()

    @pytest.mark.parametrize(
        "stage,failure_kind",
        [
            (stage, failure_kind)
            for stage in ("hash", "metadata", "mpp", "patches")
            for failure_kind in ("timeout", "network", *HTTP_OTHER_CODES)
        ]
        + [("patches", 451)],
    )
    def test_request_failures_preserve_all_old_files_and_sha(
        self, stage, failure_kind
    ) -> None:
        urls = {
            "metadata": self.url("main", "patches-bundle.json"),
            "mpp": self.bundle_data["download_url"],
            "patches": self.url("main", "patches-list.json"),
        }
        original_responses = self.responses.copy()
        if failure_kind == "timeout":
            failure = TimeoutError("Timed out")
        elif failure_kind == "network":
            failure = urllib.error.URLError("DNS failure")
        else:
            failure = self.http_error(urls.get(stage, urls["metadata"]), failure_kind)
        self.responses = original_responses.copy()
        self.fetch_hash.side_effect = failure if stage == "hash" else None
        if stage != "hash":
            self.responses[urls[stage]] = failure
        old_contents = self.seed_target()
        bundle_fetch.fetch_all_repos()
        assert load_json(self.repos_path) == self.initial_repos
        for path, content in old_contents.items():
            assert path.read_bytes() == content
        assert not self.updated_path.exists()
        self.run_process.assert_not_called()
        summary = self.summary.call_args.args[0]
        assert "https://github.com/owner/alpha:" in summary
        assert "(main)" not in summary
        expected_reason = (
            f"Request failed (HTTP {failure.code})"
            if isinstance(failure, urllib.error.HTTPError)
            else "Request failed: "
        )
        assert expected_reason in summary

    @pytest.mark.parametrize("stage", ("hash", "metadata"))
    @pytest.mark.parametrize("main_code", HTTP_UNAVAILABLE_CODES)
    @pytest.mark.parametrize("dev_code", HTTP_UNAVAILABLE_CODES)
    def test_metadata_errors_preserve_codes_in_one_entry_per_repository(
        self, stage, main_code, dev_code
    ) -> None:

        def get_hash(_source: str, _repo: str, branch: str) -> str:
            raise self.responses[self.url(branch, "patches-bundle.json")]

        save_json(self.repos_path, self.initial_repos)
        self.summary.reset_mock()
        self.fetch_hash.side_effect = get_hash if stage == "hash" else None
        for branch, code in (("main", main_code), ("dev", dev_code)):
            url = self.url(branch, "patches-bundle.json")
            self.responses[url] = self.http_error(url, code)
        with patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES):
            bundle_fetch.fetch_all_repos()
        self.summary.assert_called_once()
        summary = self.summary.call_args.args[0]
        assert "### Bundle metadata (1)" in summary
        assert summary.count("- https://") == 1
        if main_code == dev_code:
            assert "(main)" not in summary
            assert "(dev)" not in summary
            assert f"Request failed (HTTP {main_code})" in summary
        else:
            assert (
                f"https://github.com/owner/alpha: (main) Request failed (HTTP {main_code}); (dev) Request failed (HTTP {dev_code})"
                in summary
            )
        assert "HTTP 404/451" not in summary
        updated_repo = load_json(self.repos_path)["https://github.com/owner/alpha"]
        for branch in DEFAULT_BRANCHES:
            assert updated_repo[branch] is None

    @pytest.mark.parametrize("other_failure", (None, TimeoutError("Timed out")))
    def test_single_unavailable_metadata_branch_is_suppressed_in_summary(
        self, other_failure
    ) -> None:
        save_json(self.repos_path, self.initial_repos)
        self.summary.reset_mock()

        def get_hash(
            _source: str,
            _repo: str,
            branch: str,
            failure: Exception | None = other_failure,
        ) -> str | None:
            if branch == "main":
                raise self.http_error(
                    self.url(branch, "patches-bundle.json"), HTTP_NOT_FOUND
                )
            if failure:
                raise failure
            return "dev-new"

        self.fetch_hash.side_effect = get_hash
        with patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES):
            bundle_fetch.fetch_all_repos()
        if other_failure:
            self.summary.assert_called_once()
            summary = self.summary.call_args.args[0]
            assert (
                "owner/alpha: (main) Request failed (HTTP 404); (dev) Request failed: Timed out"
                in summary
            )
            assert "Timed out" in summary
            assert "404/451" not in summary
        else:
            assert self.summary.call_args.args[0] == "## 📥 Fetch (1/1):"

    def test_missing_metadata_is_grouped_by_source_and_repository(self) -> None:
        results = [
            bundle_fetch.BranchFetchResult(
                source,
                repo,
                branch,
                None,
                error_category="metadata",
                error_message="Request failed (HTTP 404)",
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
                    error_message="Request failed (HTTP 404)",
                )
            )
            errors = bundle_fetch.collect_fetch_errors(results)
        assert errors["metadata"] == [
            "https://gitlab.com/owner/alpha: Request failed (HTTP 404)"
        ]
        assert sum(len(messages) for messages in errors.values()) == 1

    @pytest.mark.parametrize("code", HTTP_UNAVAILABLE_CODES)
    def test_mpp_failures_are_reported_when_other_metadata_branch_is_missing(
        self, code
    ) -> None:
        failure = self.http_error(self.bundle_data["download_url"], code)
        save_json(self.repos_path, self.initial_repos)
        self.summary.reset_mock()

        def get_hash(_source: str, _repo: str, branch: str) -> str:
            if branch == "dev":
                raise self.http_error(
                    self.url(branch, "patches-bundle.json"), HTTP_NOT_FOUND
                )
            return "main-new"

        self.fetch_hash.side_effect = get_hash
        self.responses[self.bundle_data["download_url"]] = failure
        with patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES):
            bundle_fetch.fetch_all_repos()
        summary = self.summary.call_args.args[0]
        assert "owner/alpha: (main)" in summary
        assert "Bundle metadata (1)" in summary
        assert "Bundle download (1)" in summary
        assert f"(main) Request failed (HTTP {failure.code})" in summary
        assert "(dev) Request failed (HTTP 404)" in summary
        assert "on main and dev" not in summary

    def test_image_failure_is_reported_without_repeating_missing_metadata(self) -> None:
        self.fetch_hash.side_effect = self.http_error(
            self.url("main", "patches-bundle.json"), HTTP_NOT_FOUND
        )
        with (
            patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES),
            patch.object(
                bundle_fetch, "get_image_sha", side_effect=TimeoutError("Image timeout")
            ),
        ):
            bundle_fetch.fetch_all_repos(daily=True)
        summary = self.summary.call_args.args[0]
        assert summary.count("- https://") == 2
        assert "Bundle image (1)" in summary
        assert "Request failed: Image timeout" in summary

    def test_identical_bundle_failures_have_one_entry_without_branches(self) -> None:
        self.responses[self.bundle_data["download_url"]] = self.http_error(
            self.bundle_data["download_url"], 503
        )
        with patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES):
            bundle_fetch.fetch_all_repos()
        summary = self.summary.call_args.args[0]
        assert "Bundle download (1)" in summary
        assert "https://github.com/owner/alpha: Request failed (HTTP 503)" in summary
        assert summary.count("- https://") == 1
        assert "(main)" not in summary
        assert "(dev)" not in summary
        assert self.bundle_data["download_url"] not in summary
        assert load_json(self.repos_path) == self.initial_repos
        assert summary.startswith("## 📥 Fetch (0/1):")
        assert (
            self.fetch_request.call_args_list.count(
                call(self.bundle_data["download_url"], binary=True)
            )
            == 1
        )
        for branch in DEFAULT_BRANCHES:
            assert (
                call(self.url(branch, "patches-list.json"), binary=True)
                not in self.fetch_request.call_args_list
            )

    @pytest.mark.parametrize("result_count", (9, 10))
    def test_error_groups_collapse_independently_at_ten_repositories(
        self, result_count
    ) -> None:
        repos = {
            f"https://github.com/owner/repo-{index}": {"main": None}
            for index in range(result_count + 1)
        }
        save_json(self.repos_path, repos)

        def failed_branch(
            source: str,
            repo: str,
            branch: str,
            current_sha: str | None,
            metadata_repo: str = f"owner/repo-{result_count}",
            **_kwargs: object,
        ) -> bundle_fetch.BranchFetchResult:
            return bundle_fetch.BranchFetchResult(
                source,
                repo,
                branch,
                current_sha,
                error_category="metadata" if repo == metadata_repo else "bundle",
                error_message="Request failed (HTTP 404)",
            )

        with patch.object(
            bundle_fetch, "process_repo_branch", side_effect=failed_branch
        ):
            bundle_fetch.fetch_all_repos()
        summary = self.summary.call_args.args[0]
        metadata, download = summary.split("### Bundle download")
        assert "### Bundle metadata (1)" in metadata
        assert "<details>" not in metadata
        assert f"({result_count})" in download
        assert ("<details>" in download) == (result_count >= 10)

    def test_same_http_status_at_different_steps_keeps_both_branch_entries(
        self,
    ) -> None:
        metadata_url = self.url("main", "patches-bundle.json")
        self.responses[metadata_url] = self.http_error(metadata_url, 403)
        self.responses[self.bundle_data["download_url"]] = self.http_error(
            self.bundle_data["download_url"], 403
        )
        with patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES):
            bundle_fetch.fetch_all_repos()
        summary = self.summary.call_args.args[0]
        assert "Bundle metadata (1)" in summary
        assert "Bundle download (1)" in summary
        assert "(main) Request failed (HTTP 403)" in summary
        assert "(dev) Request failed (HTTP 403)" in summary
        assert summary.count("- https://") == len(DEFAULT_BRANCHES)
        assert "<details>" not in summary
        metadata_content, download_content = summary.split("### Bundle download")
        assert "(main) Request failed (HTTP 403)" in metadata_content
        assert "(dev) Request failed (HTTP 403)" not in metadata_content
        assert "(dev) Request failed (HTTP 403)" in download_content

    @pytest.mark.parametrize("category", ("metadata", "bundle", "patch_list"))
    def test_branch_errors_are_suppressed_when_the_other_branch_succeeds(
        self, category
    ) -> None:
        results = [
            bundle_fetch.BranchFetchResult(
                "github",
                "owner/alpha",
                "main",
                "main-old",
                error_category=category,
                error_message="Request failed (HTTP 503)",
            ),
            bundle_fetch.BranchFetchResult("github", "owner/alpha", "dev", "dev-new"),
        ]
        with patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES):
            assert not any(bundle_fetch.collect_fetch_errors(results).values())

    @pytest.mark.parametrize("code", (403, 451))
    def test_patch_list_request_errors_do_not_trigger_parsing(self, code) -> None:
        self.summary.reset_mock()
        for branch in DEFAULT_BRANCHES:
            url = self.url(branch, "patches-list.json")
            self.responses[url] = self.http_error(url, code)
        with patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES):
            bundle_fetch.fetch_all_repos()
        summary = self.summary.call_args.args[0]
        assert "Patch list (1)" in summary
        assert f"Request failed (HTTP {code})" in summary
        assert "Bundle metadata" not in summary
        assert "Bundle download" not in summary
        self.run_process.assert_not_called()
        assert load_json(self.repos_path) == self.initial_repos

    def test_both_parser_failures_report_only_one_patch_list_generation_failure(
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
        summary = self.summary.call_args.args[0]
        assert "Patch list (1)" in summary
        assert (
            "https://github.com/owner/alpha: Failed to generate `patches-list.json`"
            in summary
        )
        assert "HTTP 404" not in summary
        assert summary.startswith("## 📥 Fetch (0/1):")
        assert summary.count("- https://") == 1
        self.run_process.assert_called_once()
        for branch in DEFAULT_BRANCHES:
            assert (
                load_json(self.repos_path)["https://github.com/owner/alpha"][branch]
                is None
            )

    @pytest.mark.parametrize("code", HTTP_UNAVAILABLE_CODES)
    def test_missing_or_blocked_image_is_cleared_without_warning(self, code) -> None:
        image_url = self.url("main", "patches-bundle.png")
        with patch.object(
            bundle_fetch, "get_image_sha", side_effect=self.http_error(image_url, code)
        ):
            assert bundle_fetch.process_image("github", "owner/alpha", "image-old") == (
                "github",
                "owner/alpha",
                None,
                True,
                None,
            )
            assert bundle_fetch.process_image("github", "owner/alpha", None) == (
                "github",
                "owner/alpha",
                None,
                False,
                None,
            )

    @pytest.mark.parametrize("stage", ("hash", "metadata", "mpp"))
    @pytest.mark.parametrize("code", HTTP_UNAVAILABLE_CODES)
    def test_unavailable_metadata_and_mpp_clear_sha_without_deleting_files(
        self, stage, code
    ) -> None:
        original_responses = self.responses.copy()
        save_json(self.repos_path, self.initial_repos)
        self.responses = original_responses.copy()
        self.fetch_hash.side_effect = (
            self.http_error(self.url("main", "patches-bundle.json"), code)
            if stage == "hash"
            else None
        )
        if stage != "hash":
            url = (
                self.url("main", "patches-bundle.json")
                if stage == "metadata"
                else self.bundle_data["download_url"]
            )
            self.responses[url] = self.http_error(url, code)
        old_contents = self.seed_target()
        bundle_fetch.fetch_all_repos()
        assert (
            load_json(self.repos_path)["https://github.com/owner/alpha"]["main"] is None
        )
        for path, content in old_contents.items():
            assert path.read_bytes() == content
        self.run_process.assert_not_called()

    @pytest.mark.parametrize(
        "content",
        [
            b"{broken",
            b"[]",
            b"{}",
            json.dumps(
                {"download_url": "https://github.com/other/repo/bundle.mpp"}
            ).encode(),
        ],
    )
    def test_invalid_metadata_clears_target(self, content) -> None:
        self.responses[self.url("main", "patches-bundle.json")] = content
        result = bundle_fetch.process_repo_branch(
            "github", "owner/alpha", "main", "main-old"
        )
        assert result.new_sha is None
        assert not result.needs_parse
        assert result.error_message
        assert result.error_category == "metadata"
        assert result.error_message in ("Invalid data", "Invalid `download_url`")

    @pytest.mark.parametrize(
        "archive_kind",
        (
            "unreadable",
            "missing-manifest",
            "missing-name",
            "blank-name",
            "invalid-utf8",
        ),
    )
    def test_unreadable_or_missing_manifest_name_keeps_existing_display_name(
        self, archive_kind
    ) -> None:
        if archive_kind == "unreadable":
            content = b"not a zip archive"
        else:
            manifest = {
                "missing-manifest": None,
                "missing-name": b"Version: 1.0\n",
                "blank-name": b"Name: \n",
                "invalid-utf8": b"Name: \xff\n",
            }[archive_kind]
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                if manifest is not None:
                    archive.writestr("META-INF/MANIFEST.MF", manifest)
            content = buffer.getvalue()
        save_json(self.repos_path, self.initial_repos)
        self.responses[self.bundle_data["download_url"]] = content
        bundle_fetch.fetch_all_repos()
        updated_repo = load_json(self.repos_path)["https://github.com/owner/alpha"]
        assert updated_repo["name"] == "Alpha old"
        assert updated_repo["main"] == "main-new"
        assert (self.mpp_dir / "github~owner~alpha~main.mpp").read_bytes() == content
        assert self.summary.call_args.args[0] == "## 📥 Fetch (1/1):"
        self.run_process.assert_not_called()

    def test_name_extraction_does_not_validate_other_archive_entries(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("META-INF/MANIFEST.MF", "Name: Alpha new\n")
            archive.writestr("classes.dex", b"original dex content")
        content = buffer.getvalue().replace(
            b"original dex content", b"modified dex content"
        )
        self.responses[self.bundle_data["download_url"]] = content
        bundle_fetch.fetch_all_repos()
        updated_repo = load_json(self.repos_path)["https://github.com/owner/alpha"]
        assert updated_repo["name"] == "Alpha new"
        assert updated_repo["main"] == "main-new"
        assert self.summary.call_args.args[0] == "## 📥 Fetch (1/1):"
        self.run_process.assert_not_called()

    def test_gitlab_worker_rewrites_numeric_download_url(self) -> None:
        bundle_url = build_raw_url(
            "gitlab", "owner/alpha", "main", "patches-bundle.json"
        )
        patch_url = build_raw_url("gitlab", "owner/alpha", "main", "patches-list.json")
        numeric_url = "https://gitlab.com/api/v4/projects/123/packages/generic/bundle/latest/bundle.mpp"
        rewritten_url = numeric_url.replace("/123/", "/owner%2Falpha/")
        self.responses[bundle_url] = json.dumps({"download_url": numeric_url}).encode()
        self.responses[rewritten_url] = self.mpp_bytes
        self.responses[patch_url] = json.dumps(self.patches_data).encode()
        result = bundle_fetch.process_repo_branch(
            "gitlab", "owner/alpha", "main", "main-old"
        )
        assert load_json(self.bundles_dir / f"{result.target_name}.json") == {
            "download_url": rewritten_url
        }
        assert result.bundle_name == "Alpha new"
        assert not result.needs_parse

    def test_weekly_unavailable_mpp_clears_sha_and_retains_files(self) -> None:
        save_json(self.bundles_dir / "github~owner~alpha~main.json", self.bundle_data)
        save_json(self.patches_dir / "github~owner~alpha~main.json", self.patches_data)
        self.fetch_hash.return_value = "main-old"
        with patch.object(
            bundle_fetch,
            "get_remote_file_hash",
            side_effect=self.http_error(
                self.bundle_data["download_url"], HTTP_NOT_FOUND
            ),
        ):
            bundle_fetch.fetch_all_repos(weekly=True)
        assert (
            load_json(self.repos_path)["https://github.com/owner/alpha"]["main"] is None
        )
        assert (self.patches_dir / "github~owner~alpha~main.json").exists()
        self.fetch_request.assert_not_called()

    def test_weekly_check_failure_preserves_sha(self) -> None:
        save_json(self.bundles_dir / "github~owner~alpha~main.json", self.bundle_data)
        save_json(self.patches_dir / "github~owner~alpha~main.json", self.patches_data)
        self.fetch_hash.return_value = "main-old"
        with patch.object(
            bundle_fetch,
            "get_remote_file_hash",
            side_effect=TimeoutError("Check failed"),
        ):
            result = bundle_fetch.process_repo_branch(
                "github", "owner/alpha", "main", "main-old", weekly=True
            )
        assert result.new_sha == "main-old"
        assert not result.status_changed
        self.fetch_request.assert_not_called()

    @pytest.mark.parametrize("mode", ("daily", "weekly"))
    def test_image_updates_are_independent_of_branch_failures(self, mode) -> None:
        self.fetch_hash.side_effect = self.http_error(
            self.url("main", "patches-bundle.json"), HTTP_NOT_FOUND
        )
        with patch.object(bundle_fetch, "get_image_sha", return_value="image-new"):
            bundle_fetch.fetch_all_repos(**{mode: True})
            updated_repo = load_json(self.repos_path)["https://github.com/owner/alpha"]
            assert updated_repo["image"] == "image-new"
            assert updated_repo["main"] is None
            assert updated_repo["name"] == "Alpha old"

    def test_file_write_failure_stops_fetch(self) -> None:
        with (
            patch.object(
                bundle_fetch, "save_json", side_effect=PermissionError("Cannot write")
            ),
            pytest.raises(PermissionError),
        ):
            bundle_fetch.fetch_all_repos()
        assert load_json(self.repos_path) == self.initial_repos

    def test_missing_hash_header_is_not_a_missing_file(self) -> None:
        with patch.object(bundle_fetch.urllib.request, "urlopen") as open_url:
            open_url.return_value.__enter__.return_value.getheader.return_value = None
            with pytest.raises(ValueError, match="Missing `ETag`"):
                bundle_fetch.get_remote_file_hash(
                    self.url("main", "patches-bundle.json"), "github"
                )

    @pytest.mark.parametrize("code", HTTP_UNAVAILABLE_CODES)
    def test_hash_request_preserves_http_errors_for_the_caller(self, code) -> None:
        url = self.url("main", "patches-bundle.json")
        with patch.object(
            bundle_fetch.urllib.request,
            "urlopen",
            side_effect=self.http_error(url, code),
        ):
            with pytest.raises(urllib.error.HTTPError) as raised:
                bundle_fetch.get_remote_file_hash(url, "github")
            assert raised.value.code == code

    def test_parser_failure_stops_before_saving_repos(self) -> None:
        patch_url = self.url("main", "patches-list.json")
        self.responses[patch_url] = self.http_error(patch_url, HTTP_NOT_FOUND)
        self.run_process.side_effect = OSError("Cannot launch parser")
        with pytest.raises(OSError):
            bundle_fetch.fetch_all_repos()
        assert load_json(self.repos_path) == self.initial_repos

    def test_partial_batch_updates_only_successful_branch_name_and_saves_once(
        self,
    ) -> None:
        for branch in DEFAULT_BRANCHES:
            patch_url = self.url(branch, "patches-list.json")
            self.responses[patch_url] = self.http_error(patch_url, HTTP_NOT_FOUND)
        self.fetch_hash.side_effect = lambda _source, _repo, branch: f"{branch}-new"
        save_json(self.patches_dir / "github~owner~alpha~dev.json", self.patches_data)

        def run_parser(
            *_args: object, **_kwargs: object
        ) -> bundle_fetch.subprocess.CompletedProcess:
            assert not self.parsed_path.exists()
            save_json(
                self.patches_dir / "github~owner~alpha~main.json", self.patches_data
            )
            self.parsed_path.write_text(
                "github~owner~alpha~main.json", encoding="utf-8"
            )
            return bundle_fetch.subprocess.CompletedProcess([], 0)

        self.run_process.side_effect = run_parser
        with (
            patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES),
            patch.object(bundle_fetch, "save_json", wraps=save_json) as save,
        ):
            bundle_fetch.fetch_all_repos()
        updated_repo = load_json(self.repos_path)["https://github.com/owner/alpha"]
        assert updated_repo["main"] == "main-new"
        assert updated_repo["dev"] is None
        assert updated_repo["name"] == "Alpha new"
        assert (
            sum(
                arguments.args[0] == self.repos_path
                for arguments in save.call_args_list
            )
            == 1
        )
        self.run_process.assert_called_once()
        assert self.summary.call_args.args[0] == "## 📥 Fetch (1/1):"

    def test_success_counts_repositories_once_across_sources_and_branches(self) -> None:
        repos = self.initial_repos.copy()
        repos["https://gitlab.com/owner/alpha"] = {
            "main": "gitlab-old",
            "dev": None,
            "name": "GitLab alpha",
        }
        repos["https://github.com/owner/beta"] = {"main": "beta-old", "dev": None}
        save_json(self.repos_path, repos)

        def process_branch(
            source: str,
            repo: str,
            branch: str,
            current_sha: str | None,
            **_kwargs: object,
        ) -> bundle_fetch.BranchFetchResult:
            return bundle_fetch.BranchFetchResult(
                source,
                repo,
                branch,
                current_sha,
                error_message=None
                if source == "gitlab"
                else "Request failed (HTTP 503)",
                error_category=None if source == "gitlab" else "metadata",
            )

        with (
            patch.object(
                bundle_fetch, "process_repo_branch", side_effect=process_branch
            ),
            patch.object(
                bundle_fetch, "get_image_sha", side_effect=TimeoutError("Image timeout")
            ),
        ):
            bundle_fetch.fetch_all_repos(daily=True)
        summary = self.summary.call_args.args[0]
        assert summary.startswith("## 📥 Fetch (1/3):")
        assert "Bundle image (3)" in summary
        assert load_json(self.repos_path) == repos

    def test_empty_repository_list_still_reports_zero_counts(self) -> None:
        save_json(self.repos_path, {})
        bundle_fetch.fetch_all_repos()
        assert self.summary.call_args.args[0] == "## 📥 Fetch (0/0):"
        self.fetch_hash.assert_not_called()
        self.fetch_request.assert_not_called()

    def test_main_name_wins_independently_of_worker_completion_order(self) -> None:

        def process(
            source: str, repo: str, branch: str, _sha: str | None, **_kwargs: object
        ) -> bundle_fetch.BranchFetchResult:
            return bundle_fetch.BranchFetchResult(
                source,
                repo,
                branch,
                "new",
                status_changed=True,
                bundle_name=f"{branch} name",
            )

        with (
            patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES),
            patch.object(bundle_fetch, "process_repo_branch", side_effect=process),
        ):
            bundle_fetch.fetch_all_repos()
        assert (
            load_json(self.repos_path)["https://github.com/owner/alpha"]["name"]
            == "main name"
        )

    def test_dev_update_downloads_bundle_but_keeps_existing_main_name(self) -> None:
        self.seed_target()
        save_json(self.bundles_dir / "github~owner~alpha~main.json", self.bundle_data)
        self.fetch_hash.side_effect = lambda _source, _repo, branch: (
            "main-old" if branch == "main" else "dev-new"
        )
        with patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES):
            bundle_fetch.fetch_all_repos()
        assert (
            load_json(self.repos_path)["https://github.com/owner/alpha"]["name"]
            == "Alpha old"
        )
        self.fetch_request.assert_any_call(
            self.url("dev", "patches-list.json"), binary=True
        )
        assert (self.mpp_dir / "github~owner~alpha~dev.mpp").is_file()

    def test_switch_to_unchanged_dev_reads_its_name_when_local_mpp_is_absent(
        self,
    ) -> None:
        save_json(self.bundles_dir / "github~owner~alpha~dev.json", self.bundle_data)
        save_json(self.patches_dir / "github~owner~alpha~dev.json", self.patches_data)

        def hash_for_branch(_source: str, _repo: str, branch: str) -> str:
            if branch == "main":
                raise self.http_error(
                    self.url(branch, "patches-bundle.json"), HTTP_NOT_FOUND
                )
            return "dev-old"

        self.fetch_hash.side_effect = hash_for_branch
        with patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES):
            bundle_fetch.fetch_all_repos()
        assert (
            load_json(self.repos_path)["https://github.com/owner/alpha"]["name"]
            == "Alpha new"
        )
        self.fetch_request.assert_called_once_with(
            self.bundle_data["download_url"], binary=True
        )

    def test_new_empty_repository_entry_is_fetched(self) -> None:
        save_json(self.repos_path, {"https://github.com/owner/alpha": {}})
        bundle_fetch.fetch_all_repos()
        assert (
            load_json(self.repos_path)["https://github.com/owner/alpha"]["main"]
            == "main-new"
        )
        assert (
            load_json(self.repos_path)["https://github.com/owner/alpha"]["name"]
            == "Alpha new"
        )

    def test_confirmed_rename_allows_download_from_the_new_repository(self) -> None:
        new_url = "https://github.com/owner/new/releases/latest/bundle.mpp"
        self.responses[self.url("main", "patches-bundle.json")] = json.dumps(
            {"download_url": new_url}
        ).encode()
        self.responses[new_url] = self.mpp_bytes
        result = bundle_fetch.process_repo_branch(
            "github", "owner/alpha", "main", "main-old", renamed_repo="owner/new"
        )
        assert result.new_sha == "main-new"
        assert result.error_message is None


class TestRepositoryMetadataRefresh:
    @pytest.fixture(autouse=True)
    def prepare(self) -> None:
        self.url = "https://github.com/owner/alpha"
        self.metadata = {
            "main": "sha",
            "dev": None,
            "name": "Alpha",
            "stars": 17,
            "description": "Old",
            "avatarUrl": "https://example.com/old.png",
        }

    def test_default_skips_complete_metadata_and_refreshes_missing_fields(self) -> None:
        repos = {self.url: dict(self.metadata)}
        with patch.object(
            bundle_fetch,
            "fetch_repo_details",
            return_value={"stars": 23, "description": "New"},
        ) as request:
            assert bundle_fetch.refresh_repo_metadata(repos, False) == []
            request.assert_not_called()
            repos[self.url].pop("stars")
            bundle_fetch.refresh_repo_metadata(repos, False)
            request.assert_called_once_with(self.url)
        assert repos[self.url]["stars"] == 23

    @pytest.mark.parametrize(
        "reason",
        (
            "Request failed (HTTP 404)",
            "Request failed (HTTP 451)",
            "Request failed: timed out",
        ),
    )
    def test_request_errors_preserve_all_metadata_and_pending_rename(
        self, reason
    ) -> None:
        self.metadata["renamedTo"] = "https://github.com/owner/new"
        with patch.object(
            bundle_fetch, "fetch_repo_details", return_value={"error": reason}
        ):
            repos = {self.url: dict(self.metadata)}
            assert bundle_fetch.refresh_repo_metadata(repos, True) == [
                f"{self.url}: {reason}"
            ]
            assert repos[self.url] == self.metadata

    def test_archived_false_removes_flag_and_rename_only_records_destination(
        self,
    ) -> None:
        repos = {self.url: {**self.metadata, "isArchived": True}}
        with patch.object(
            bundle_fetch,
            "fetch_repo_details",
            return_value={"full_name": "owner/new", "stars": 23},
        ):
            warnings = bundle_fetch.refresh_repo_metadata(repos, True)
        assert "isArchived" not in repos[self.url]
        assert repos[self.url]["renamedTo"] == "https://github.com/owner/new"
        assert set(repos) == {self.url}
        assert "Renamed to" in warnings[0]
        with patch.object(
            bundle_fetch,
            "fetch_repo_details",
            return_value={"full_name": "OWNER/ALPHA", "is_archived": True},
        ):
            warnings = bundle_fetch.refresh_repo_metadata(repos, True)
        assert "renamedTo" not in repos[self.url]
        assert repos[self.url]["isArchived"]
        assert "Repository is archived" in warnings[0]

    def test_null_hashes_do_not_trigger_repository_request(self) -> None:
        with patch.object(bundle_fetch, "fetch_repo_details") as request:
            assert bundle_fetch.refresh_repo_metadata({self.url: {}}, True) == []
            request.assert_not_called()

    def test_fetch_persists_metadata_once_and_defers_custom_source_changes(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path
        repos_path = root / "repos.json"
        custom_path = root / "custom.json"
        save_json(repos_path, {self.url: {"main": "sha", "name": "Alpha"}})
        save_json(custom_path, {self.url: {"note": "Keep me"}})
        custom_before = custom_path.read_bytes()

        def unchanged(
            source: str,
            repo: str,
            branch: str,
            current_sha: str | None,
            **kwargs: object,
        ) -> bundle_fetch.BranchFetchResult:
            assert kwargs["renamed_repo"] == "owner/new"
            return bundle_fetch.BranchFetchResult(source, repo, branch, current_sha)

        with (
            patch.multiple(
                bundle_fetch,
                REPOS_JSON_PATH=repos_path,
                BUNDLES_DIR=root / "bundles",
                PATCHES_DIR=root / "patches",
                MPP_DIR=root / "mpp",
            ),
            patch.object(bundle_fetch, "process_repo_branch", side_effect=unchanged),
            patch.object(bundle_fetch, "run_bundle_parser"),
            patch.object(
                bundle_fetch,
                "fetch_repo_details",
                return_value={
                    "full_name": "owner/new",
                    "stars": 23,
                    "description": "New",
                    "avatar_url": "https://example.com/avatar.png",
                },
            ) as request,
            patch.object(bundle_fetch, "append_step_summary") as summary,
            patch.object(bundle_fetch, "save_json", wraps=save_json) as save,
        ):
            bundle_fetch.fetch_all_repos()
            request.assert_called_once_with(self.url)
            save.assert_called_once()
            assert "Repository metadata (1)" in summary.call_args.args[0]
        metadata = load_json(repos_path)[self.url]
        assert metadata["renamedTo"] == "https://github.com/owner/new"
        assert metadata["main"] == "sha"
        assert metadata["stars"] == 23
        assert custom_path.read_bytes() == custom_before
