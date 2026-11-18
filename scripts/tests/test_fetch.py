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
    def test_changed_metadata_uses_one_conditional_get_with_response_etag(
        self, etag
    ) -> None:
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
            assert (
                other.result(timeout=DOWNLOAD_WAIT_TIMEOUT_SECONDS)
                == other_url.encode()
            )
        finally:
            release_download.set()
        for result in (first, second):
            if failure is None:
                assert (
                    result.result(timeout=DOWNLOAD_WAIT_TIMEOUT_SECONDS)
                    == shared_url.encode()
                )
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
        self.initial_repos: dict[str, dict[str, str | None]] = {
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
                return_value={"error": "HTTP Error 503: Request failed"},
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
        self.responses: dict[str, bytes | Exception] = {
            self.bundle_data["download_url"]: self.mpp_bytes
        }
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
            patch.object(bundle_fetch, "request", side_effect=self.download)
        )
        self.fetch_hash = self.patch_context.enter_context(
            patch.object(bundle_fetch, "get_remote_file_hash", return_value="main-new")
        )
        self.github_metadata_request = self.patch_context.enter_context(
            patch.object(
                bundle_fetch, "get_github_bundle", side_effect=self.github_metadata
            )
        )
        self.patch_context.enter_context(
            patch.object(bundle_fetch, "get_image_sha", return_value="image-old")
        )
        self.patch_context.enter_context(
            patch.object(bundle_fetch, "append_step_summary")
        )
        self.run_process = self.patch_context.enter_context(
            patch.object(bundle_fetch.subprocess, "run")
        )

    def url(self, branch: str, filename: str) -> str:
        url = build_raw_url("github", "owner/alpha", branch, filename)
        assert url is not None
        return url

    def download(self, url: str) -> httpx2.Response:
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return httpx2.Response(200, content=response)

    def github_metadata(
        self, url: str, current_sha: str | None
    ) -> tuple[str, bytes | None]:
        remote_sha = self.fetch_hash(url, "github")
        if current_sha and remote_sha == current_sha:
            return (current_sha, None)
        return (remote_sha, self.fetch_request(url).content)

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

        def download(url: str) -> httpx2.Response:
            if url in patch_urls:
                assert threading.current_thread() is not threading.main_thread()
                barrier.wait(timeout=PATCH_LIST_BARRIER_TIMEOUT_SECONDS)
            return self.download(url)

        self.fetch_request.side_effect = download
        self.fetch_hash.side_effect = lambda url, _source: (
            "dev-new" if "/dev/" in url else "main-new"
        )
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
        assert (
            self.fetch_request.call_args_list.count(
                call(self.bundle_data["download_url"])
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
            assert self.fetch_request.call_args_list.count(call(url)) == 1
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
                call(self.bundle_data["download_url"])
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

    def test_unchanged_target_skips_downloads_without_local_mpp(self) -> None:
        save_json(self.bundles_dir / "github~owner~alpha~main.json", self.bundle_data)
        save_json(self.patches_dir / "github~owner~alpha~main.json", self.patches_data)
        self.fetch_hash.return_value = "main-old"
        original_content = self.repos_path.read_bytes()
        bundle_fetch.fetch_all_repos()
        self.fetch_request.assert_not_called()
        self.run_process.assert_not_called()
        assert self.repos_path.read_bytes() == original_content
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
            call(self.url("main", "patches-bundle.json"))
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
    def test_errors_are_deduplicated_per_repository_and_stage(
        self, categories, expected_counts
    ) -> None:
        results = [
            bundle_fetch.BranchFetchResult(
                "github",
                "owner/alpha",
                branch,
                None,
                error_category=category,
                error_message="HTTP 503",
            )
            for branch, category in zip(DEFAULT_BRANCHES, categories, strict=True)
        ]
        with patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES):
            errors = bundle_fetch.collect_fetch_errors(results)
        assert {
            category: len(messages) for category, messages in errors.items() if messages
        } == expected_counts
        assert all(
            "https://github.com/owner/alpha" in message
            for messages in errors.values()
            for message in messages
        )

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
                error_message="HTTP Error 503: Request failed",
            ),
            bundle_fetch.BranchFetchResult("github", "owner/alpha", "dev", "dev-new"),
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
            assert (
                load_json(self.repos_path)["https://github.com/owner/alpha"][branch]
                is None
            )

    @pytest.mark.parametrize(
        "stage,code", (("hash", 404), ("metadata", 451), ("mpp", 404))
    )
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
            b"{}",
            json.dumps(
                {"download_url": "https://github.com/other/repo/bundle.mpp"}
            ).encode(),
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
            side_effect=lambda url: {"full_name": parse_repo_url(url)[1]},
        ):
            result = bundle_fetch.process_repo_branch(
                "github", "owner/alpha", "main", "main-old"
            )
        assert result.new_sha is None
        assert not result.needs_parse
        assert result.error_message
        assert result.error_category == "metadata"
        assert result.error_message in ("Invalid data", "Invalid `download_url`")

    def test_unreadable_manifest_keeps_existing_display_name(self) -> None:
        self.responses[self.bundle_data["download_url"]] = b"not a zip archive"
        bundle_fetch.fetch_all_repos()
        updated_repo = load_json(self.repos_path)["https://github.com/owner/alpha"]
        assert updated_repo["name"] == "Alpha old"
        assert updated_repo["main"] == "main-new"

    @pytest.mark.parametrize(
        "download_url",
        (
            "https://gitlab.com/api/v4/projects/123/packages/generic/bundle/latest/bundle.mpp",
            "https://gitlab.com/-/project/123/uploads/abc/bundle.mpp",
        ),
    )
    @pytest.mark.parametrize(
        "project_id,expected_sha",
        ((123, "main-new"), (456, None), (None, "main-old")),
    )
    def test_gitlab_numeric_download_url_verifies_project_and_preserves_url(
        self, download_url, project_id, expected_sha
    ) -> None:
        bundle_url = build_raw_url(
            "gitlab", "owner/alpha", "main", "patches-bundle.json"
        )
        patch_url = build_raw_url("gitlab", "owner/alpha", "main", "patches-list.json")
        assert bundle_url is not None and patch_url is not None
        self.responses[bundle_url] = json.dumps({"download_url": download_url}).encode()
        self.responses[download_url] = self.mpp_bytes
        self.responses[patch_url] = json.dumps(self.patches_data).encode()
        with patch.object(
            bundle_fetch,
            "fetch_repo_details",
            return_value={"project_id": project_id, "full_name": "owner/alpha"},
        ) as lookup:
            result = bundle_fetch.process_repo_branch(
                "gitlab", "owner/alpha", "main", "main-old"
            )
        lookup.assert_called_once_with("https://gitlab.com/owner/alpha")
        assert result.new_sha == expected_sha
        assert (call(download_url) in self.fetch_request.call_args_list) == (
            expected_sha == "main-new"
        )
        if expected_sha == "main-new":
            assert load_json(self.bundles_dir / f"{result.target_name}.json") == {
                "download_url": download_url
            }
            assert result.bundle_name == "Alpha new"
            assert not result.needs_parse
        else:
            assert result.error_category == "metadata"

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

    def test_image_updates_are_independent_of_branch_failures(self) -> None:
        self.fetch_hash.side_effect = self.http_error(
            self.url("main", "patches-bundle.json"), HTTP_NOT_FOUND
        )
        with patch.object(bundle_fetch, "get_image_sha", return_value="image-new"):
            bundle_fetch.fetch_all_repos(daily=True)
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
        self.fetch_hash.side_effect = lambda url, _source: (
            "dev-new" if "/dev/" in url else "main-new"
        )
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
        ):
            bundle_fetch.fetch_all_repos()
        updated_repo = load_json(self.repos_path)["https://github.com/owner/alpha"]
        assert updated_repo["main"] == "main-new"
        assert updated_repo["dev"] is None
        assert updated_repo["name"] == "Alpha new"
        self.run_process.assert_called_once()

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
        self.fetch_hash.side_effect = lambda url, _source: (
            "main-old" if "/main/" in url else "dev-new"
        )
        with patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES):
            bundle_fetch.fetch_all_repos()
        assert (
            load_json(self.repos_path)["https://github.com/owner/alpha"]["name"]
            == "Alpha old"
        )
        self.fetch_request.assert_any_call(self.url("dev", "patches-list.json"))
        assert (self.mpp_dir / "github~owner~alpha~dev.mpp").is_file()

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

    @pytest.mark.parametrize("source", ("github", "gitlab"))
    @pytest.mark.parametrize("direction", ("forward", "reverse"))
    def test_mismatched_asset_uses_confirmed_repository_identity(
        self, source, direction
    ) -> None:
        asset_repo = "owner/new" if direction == "forward" else "owner/old"
        canonical_repo = "owner/new" if direction == "forward" else "owner/alpha"
        asset_url = (
            f"https://github.com/{asset_repo}/releases/download/v1/bundle.mpp"
            if source == "github"
            else f"https://gitlab.com/{asset_repo}/-/releases/v1/downloads/bundle.mpp"
        )
        metadata_url = build_raw_url(
            source, "owner/alpha", "main", "patches-bundle.json"
        )
        patches_url = build_raw_url(source, "owner/alpha", "main", "patches-list.json")
        assert metadata_url is not None and patches_url is not None
        self.responses[metadata_url] = json.dumps({"download_url": asset_url}).encode()
        self.responses[patches_url] = json.dumps(self.patches_data).encode()
        self.responses[asset_url] = self.mpp_bytes
        with patch.object(
            bundle_fetch,
            "fetch_repo_details",
            return_value={"full_name": canonical_repo},
        ) as request:
            result = bundle_fetch.process_repo_branch(
                source, "owner/alpha", "main", "main-old"
            )
        assert result.new_sha == "main-new"
        assert result.error_message is None
        assert result.renamed_to == (
            f"https://{source}.com/owner/new" if direction == "forward" else None
        )
        assert request.call_count == (1 if direction == "forward" else 2)

    @pytest.mark.parametrize(
        "lookup,details", (("source", {"error": "Unavailable"}), ("asset", {}))
    )
    def test_unverified_repository_identity_preserves_saved_target(
        self, lookup, details
    ) -> None:
        self.responses[self.url("main", "patches-bundle.json")] = json.dumps(
            {"download_url": "https://github.com/owner/new/bundle.mpp"}
        ).encode()
        old_contents = self.seed_target()
        responses = (
            [details] if lookup == "source" else [{"full_name": "owner/alpha"}, details]
        )
        with patch.object(bundle_fetch, "fetch_repo_details", side_effect=responses):
            result = bundle_fetch.process_repo_branch(
                "github", "owner/alpha", "main", "main-old"
            )
        assert result.new_sha == "main-old"
        assert not result.status_changed
        assert not result.renamed_to
        assert result.error_message
        for path, content in old_contents.items():
            assert path.read_bytes() == content

    def test_reused_alias_is_rejected_when_api_confirms_different_repository(
        self,
    ) -> None:
        self.responses[self.url("main", "patches-bundle.json")] = json.dumps(
            {"download_url": "https://github.com/owner/old/bundle.mpp"}
        ).encode()
        with patch.object(
            bundle_fetch,
            "fetch_repo_details",
            side_effect=[{"full_name": "owner/alpha"}, {"full_name": "owner/old"}],
        ):
            result = bundle_fetch.process_repo_branch(
                "github", "owner/alpha", "main", "main-old"
            )
        assert result.new_sha is None
        assert result.error_message == "Invalid `download_url`"
        self.fetch_request.assert_called_once_with(
            self.url("main", "patches-bundle.json")
        )

    def test_fetch_records_verified_rename_without_modifying_local_keys(self) -> None:
        asset_url = "https://github.com/owner/new/releases/v1/bundle.mpp"
        self.responses[self.url("main", "patches-bundle.json")] = json.dumps(
            {"download_url": asset_url}
        ).encode()
        self.responses[asset_url] = self.mpp_bytes
        save_json(self.repos_path, {"https://github.com/owner/alpha": {}})
        with patch.object(
            bundle_fetch, "fetch_repo_details", return_value={"full_name": "owner/new"}
        ) as request:
            bundle_fetch.fetch_all_repos()
        repos = load_json(self.repos_path)
        assert set(repos) == {"https://github.com/owner/alpha"}
        assert (
            repos["https://github.com/owner/alpha"]["renamedTo"]
            == "https://github.com/owner/new"
        )
        assert repos["https://github.com/owner/alpha"]["main"] == "main-new"
        assert (self.bundles_dir / "github~owner~alpha~main.json").is_file()
        request.assert_called_once_with("https://github.com/owner/alpha")


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

    def test_refresh_failure_preserves_metadata_and_pending_rename(self) -> None:
        self.metadata["renamedTo"] = "https://github.com/owner/new"
        with patch.object(
            bundle_fetch, "fetch_repo_details", return_value={"error": "Unavailable"}
        ):
            repos = {self.url: dict(self.metadata)}
            assert bundle_fetch.refresh_repo_metadata(repos, True)
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
        assert warnings
        with patch.object(
            bundle_fetch,
            "fetch_repo_details",
            return_value={"full_name": "OWNER/ALPHA", "is_archived": True},
        ):
            warnings = bundle_fetch.refresh_repo_metadata(repos, True)
        assert "renamedTo" not in repos[self.url]
        assert repos[self.url]["isArchived"]
        assert warnings

    def test_fetch_persists_metadata_without_changing_custom_sources(
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
            patch.object(bundle_fetch, "append_step_summary"),
        ):
            bundle_fetch.fetch_all_repos()
            request.assert_called_once_with(self.url)
        metadata = load_json(repos_path)[self.url]
        assert metadata["renamedTo"] == "https://github.com/owner/new"
        assert metadata["main"] == "sha"
        assert metadata["stars"] == 23
        assert custom_path.read_bytes() == custom_before
