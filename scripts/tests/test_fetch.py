import io
import json
import tempfile
import threading
import unittest
import urllib.error
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, call, patch

import fetch as bundle_fetch
from utils import DEFAULT_BRANCHES, build_raw_url, load_json, save_json

PATCH_LIST_BARRIER_TIMEOUT_SECONDS = 5
DOWNLOAD_WAIT_TIMEOUT_SECONDS = 5
HTTP_NOT_FOUND = 404
HTTP_UNAVAILABLE_CODES = (404, 451)
HTTP_OTHER_CODES = (403, 429, 500, 503)


class GithubBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.url = build_raw_url("github", "owner/alpha", "main", "patches-bundle.json")
        request_patcher = patch.object(bundle_fetch.urllib.request, "urlopen")
        self.open_url = request_patcher.start()
        self.addCleanup(request_patcher.stop)
        self.response = self.open_url.return_value.__enter__.return_value
        self.response.getheader.return_value = '"new-hash"'
        self.response.read.return_value = b'{"download_url": "bundle.mpp"}'

    def test_changed_metadata_uses_one_conditional_get_with_response_etag(self) -> None:
        result = bundle_fetch.get_github_bundle(self.url, "old-hash")
        self.assertEqual(result, ("new-hash", self.response.read.return_value))
        self.open_url.assert_called_once()
        request = self.open_url.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("If-none-match"), '"old-hash"')
        self.response.read.assert_called_once()

    def test_unconfirmed_metadata_uses_unconditional_get(self) -> None:
        bundle_fetch.get_github_bundle(self.url, None)
        self.assertIsNone(self.open_url.call_args.args[0].get_header("If-none-match"))
        self.response.read.assert_called_once()

    def test_not_modified_preserves_hash_without_reading_body(self) -> None:
        body = io.BytesIO()
        self.open_url.side_effect = urllib.error.HTTPError(
            self.url, 304, "Not Modified", None, body
        )
        self.assertEqual(
            bundle_fetch.get_github_bundle(self.url, "old-hash"),
            ("old-hash", None),
        )
        self.open_url.assert_called_once()
        self.response.read.assert_not_called()
        self.assertTrue(body.closed)

    def test_http_errors_propagate_with_actual_status(self) -> None:
        for code in (304, *HTTP_UNAVAILABLE_CODES, *HTTP_OTHER_CODES):
            with self.subTest(code=code):
                error = urllib.error.HTTPError(
                    self.url, code, "Request failed", None, None
                )
                self.addCleanup(error.close)
                self.open_url.side_effect = error
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    bundle_fetch.get_github_bundle(self.url, None)
                self.assertIs(raised.exception, error)

    def test_network_errors_propagate_without_retry(self) -> None:
        error = urllib.error.URLError("DNS failure")
        self.open_url.side_effect = error
        with self.assertRaises(urllib.error.URLError) as raised:
            bundle_fetch.get_github_bundle(self.url, "old-hash")
        self.assertIs(raised.exception, error)
        self.open_url.assert_called_once()

    def test_missing_etag_is_reported_before_reading_body(self) -> None:
        self.response.getheader.return_value = None
        with self.assertRaisesRegex(ValueError, "Missing `ETag`"):
            bundle_fetch.get_github_bundle(self.url, None)
        self.response.read.assert_not_called()


class BundleDownloadsTests(unittest.TestCase):
    def test_concurrent_targets_share_download_without_blocking_other_urls(
        self,
    ) -> None:
        shared_url = "https://example.com/shared.mpp"
        other_url = "https://example.com/other.mpp"
        download_started = threading.Event()
        release_download = threading.Event()
        downloads = bundle_fetch.BundleDownloads()

        def download(url: str, *, binary: bool) -> bytes:
            self.assertTrue(binary)
            if url == shared_url:
                download_started.set()
                self.assertTrue(
                    release_download.wait(timeout=DOWNLOAD_WAIT_TIMEOUT_SECONDS)
                )
            return url.encode()

        with (
            patch.object(bundle_fetch, "fetch", side_effect=download) as request,
            ThreadPoolExecutor(max_workers=3) as executor,
        ):
            first = executor.submit(downloads.download, shared_url)
            try:
                self.assertTrue(
                    download_started.wait(timeout=DOWNLOAD_WAIT_TIMEOUT_SECONDS)
                )
                second = executor.submit(downloads.download, shared_url)
                other = executor.submit(downloads.download, other_url)
                self.assertEqual(
                    other.result(timeout=DOWNLOAD_WAIT_TIMEOUT_SECONDS),
                    other_url.encode(),
                )
            finally:
                release_download.set()
            self.assertEqual(first.result(), shared_url.encode())
            self.assertEqual(second.result(), shared_url.encode())
        self.assertEqual(request.call_count, 2)


class BundleFetchTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.root = Path(temporary_directory.name)
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
        repo_info_patcher = patch.object(
            bundle_fetch,
            "fetch_repo_details",
            return_value={"error": "Request failed (HTTP 503)"},
        )
        repo_info_patcher.start()
        self.addCleanup(repo_info_patcher.stop)
        refresh_patcher = patch.object(
            bundle_fetch, "refresh_repo_metadata", return_value=[]
        )
        refresh_patcher.start()
        self.addCleanup(refresh_patcher.stop)
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
        path_patcher = patch.multiple(
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
        path_patcher.start()
        self.addCleanup(path_patcher.stop)
        request_patcher = patch.object(bundle_fetch, "fetch", side_effect=self.download)
        self.fetch_request = request_patcher.start()
        self.addCleanup(request_patcher.stop)
        self.fetch_hash = Mock(return_value="main-new")
        hash_patcher = patch.object(
            bundle_fetch, "get_file_sha", side_effect=self.fetch_hash
        )
        hash_patcher.start()
        self.addCleanup(hash_patcher.stop)
        github_patcher = patch.object(
            bundle_fetch, "get_github_bundle", side_effect=self.github_metadata
        )
        self.github_metadata_request = github_patcher.start()
        self.addCleanup(github_patcher.stop)
        image_patcher = patch.object(
            bundle_fetch, "get_image_sha", return_value="image-old"
        )
        image_patcher.start()
        self.addCleanup(image_patcher.stop)
        summary_patcher = patch.object(bundle_fetch, "append_step_summary")
        self.summary = summary_patcher.start()
        self.addCleanup(summary_patcher.stop)
        process_patcher = patch.object(bundle_fetch.subprocess, "run")
        self.run_process = process_patcher.start()
        self.addCleanup(process_patcher.stop)

    def url(self, branch: str, filename: str) -> str:
        return build_raw_url("github", "owner/alpha", branch, filename)

    def download(self, url: str, binary: bool = False) -> str | bytes:
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response if binary else response.decode()

    def http_error(self, url: str, code: int) -> urllib.error.HTTPError:
        error = urllib.error.HTTPError(url, code, "Request failed", None, None)
        self.addCleanup(error.close)
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
            return current_sha, None
        return remote_sha, self.fetch_request(url, binary=True)

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
                self.assertIsNot(threading.current_thread(), threading.main_thread())
                barrier.wait(timeout=PATCH_LIST_BARRIER_TIMEOUT_SECONDS)
            return self.download(url, binary=binary)

        self.fetch_request.side_effect = download
        self.fetch_hash.side_effect = lambda _source, _repo, branch: f"{branch}-new"
        self.updated_path.write_text("mpp/stale.mpp", encoding="utf-8")
        with patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES):
            bundle_fetch.fetch_all_repos()
        for branch in DEFAULT_BRANCHES:
            file_prefix = f"github~owner~alpha~{branch}"
            self.assertEqual(
                load_json(self.bundles_dir / f"{file_prefix}.json"), self.bundle_data
            )
            self.assertEqual(
                load_json(self.patches_dir / f"{file_prefix}.json"), self.patches_data
            )
            self.assertEqual(
                (self.mpp_dir / f"{file_prefix}.mpp").read_bytes(), self.mpp_bytes
            )
        updated_repo = load_json(self.repos_path)["https://github.com/owner/alpha"]
        self.assertEqual(updated_repo["name"], "Alpha new")
        for branch in DEFAULT_BRANCHES:
            self.assertEqual(updated_repo[branch], f"{branch}-new")
        self.assertFalse(self.updated_path.exists())
        self.run_process.assert_not_called()
        self.assertEqual(self.summary.call_args.args[0], "## 📥 Fetch (1/1):")
        self.assertEqual(
            self.fetch_request.call_args_list.count(
                call(self.bundle_data["download_url"], binary=True)
            ),
            1,
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
            self.assertEqual(
                self.fetch_request.call_args_list.count(call(url, binary=True)),
                1,
            )
        for branch in DEFAULT_BRANCHES:
            self.assertEqual(
                (self.mpp_dir / f"github~owner~alpha~{branch}.mpp").read_bytes(),
                self.mpp_bytes,
            )

    def test_bundle_downloads_are_not_reused_between_fetch_runs(self) -> None:
        bundle_fetch.fetch_all_repos()
        save_json(self.repos_path, self.initial_repos)
        bundle_fetch.fetch_all_repos()
        self.assertEqual(
            self.fetch_request.call_args_list.count(
                call(self.bundle_data["download_url"], binary=True)
            ),
            2,
        )

    def test_only_patch_list_404_queues_downloaded_mpp(self) -> None:
        url = self.url("main", "patches-list.json")
        self.responses[url] = self.http_error(url, HTTP_NOT_FOUND)
        result = bundle_fetch.process_repo_branch(
            "github", "owner/alpha", "main", "main-old"
        )
        self.assertTrue(result.needs_parse)
        self.assertEqual(result.new_sha, "main-new")
        self.assertEqual(
            (self.mpp_dir / f"{result.target_name}.mpp").read_bytes(), self.mpp_bytes
        )
        self.run_process.assert_not_called()

    def test_downloaded_patch_list_is_saved_verbatim_without_validation(self) -> None:
        for content in (b"{broken", b"{}", b'{"patches": []}', b"", b"\xff"):
            with self.subTest(content=content):
                save_json(self.repos_path, self.initial_repos)
                self.responses[self.url("main", "patches-list.json")] = content
                bundle_fetch.fetch_all_repos()
                self.assertEqual(
                    (self.patches_dir / "github~owner~alpha~main.json").read_bytes(),
                    content,
                )
                self.assertEqual(
                    load_json(self.repos_path)["https://github.com/owner/alpha"][
                        "main"
                    ],
                    "main-new",
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
        self.assertEqual(self.repos_path.read_bytes(), original_content)
        self.assertEqual(self.summary.call_args.args[0], "## 📥 Fetch (1/1):")
        self.github_metadata_request.assert_called_once_with(
            self.url("main", "patches-bundle.json"), "main-old"
        )

    def test_missing_json_refetches_even_with_unchanged_hash(self) -> None:
        self.fetch_hash.return_value = "main-old"
        for missing_directory in (self.bundles_dir, self.patches_dir):
            with self.subTest(missing_directory=missing_directory.name):
                self.seed_target()
                (missing_directory / "github~owner~alpha~main.json").unlink()
                self.fetch_request.reset_mock()
                self.github_metadata_request.reset_mock()
                bundle_fetch.fetch_all_repos()
                self.assertEqual(
                    load_json(self.patches_dir / "github~owner~alpha~main.json"),
                    self.patches_data,
                )
                self.assertEqual(self.fetch_request.call_count, 3)
                self.github_metadata_request.assert_called_once_with(
                    self.url("main", "patches-bundle.json"), None
                )

    def test_null_sha_refetches_despite_existing_local_files(self) -> None:
        self.seed_target()
        result = bundle_fetch.process_repo_branch("github", "owner/alpha", "main", None)
        self.github_metadata_request.assert_called_once_with(
            self.url("main", "patches-bundle.json"), None
        )
        self.assertEqual(result.new_sha, "main-new")
        self.assertTrue(result.status_changed)

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
        self.assertTrue(result.status_changed)
        self.assertEqual(result.bundle_name, "Alpha new")
        self.assertNotIn(
            call(self.url("main", "patches-bundle.json"), binary=True),
            self.fetch_request.call_args_list,
        )

    def test_gitlab_unchanged_metadata_still_skips_get(self) -> None:
        self.fetch_hash.return_value = "main-old"
        for directory in (self.bundles_dir, self.patches_dir):
            save_json(directory / "gitlab~owner~alpha~main.json", {})
        result = bundle_fetch.process_repo_branch(
            "gitlab", "owner/alpha", "main", "main-old"
        )
        self.assertEqual(result.new_sha, "main-old")
        self.assertFalse(result.status_changed)
        self.fetch_hash.assert_called_once_with("gitlab", "owner/alpha", "main")
        self.github_metadata_request.assert_not_called()
        self.fetch_request.assert_not_called()

    def test_request_failures_preserve_all_old_files_and_sha(self) -> None:
        urls = {
            "metadata": self.url("main", "patches-bundle.json"),
            "mpp": self.bundle_data["download_url"],
            "patches": self.url("main", "patches-list.json"),
        }
        original_responses = self.responses.copy()
        for stage in ("hash", *urls):
            failures = [TimeoutError("Timed out"), urllib.error.URLError("DNS failure")]
            failures.extend(
                self.http_error(urls.get(stage, urls["metadata"]), code)
                for code in HTTP_OTHER_CODES
            )
            if stage == "patches":
                failures.append(self.http_error(urls[stage], 451))
            for failure in failures:
                with self.subTest(stage=stage, failure=str(failure)):
                    self.responses = original_responses.copy()
                    self.fetch_hash.side_effect = failure if stage == "hash" else None
                    if stage != "hash":
                        self.responses[urls[stage]] = failure
                    old_contents = self.seed_target()
                    bundle_fetch.fetch_all_repos()
                    self.assertEqual(load_json(self.repos_path), self.initial_repos)
                    for path, content in old_contents.items():
                        self.assertEqual(path.read_bytes(), content)
                    self.assertFalse(self.updated_path.exists())
                    self.run_process.assert_not_called()
                    summary = self.summary.call_args.args[0]
                    self.assertIn("https://github.com/owner/alpha:", summary)
                    self.assertNotIn("(main)", summary)
                    expected_reason = (
                        f"Request failed (HTTP {failure.code})"
                        if isinstance(failure, urllib.error.HTTPError)
                        else "Request failed: "
                    )
                    self.assertIn(expected_reason, summary)

    def test_metadata_errors_preserve_codes_in_one_entry_per_repository(
        self,
    ) -> None:
        def get_hash(_source: str, _repo: str, branch: str) -> str:
            raise self.responses[self.url(branch, "patches-bundle.json")]

        for stage in ("hash", "metadata"):
            for main_code in HTTP_UNAVAILABLE_CODES:
                for dev_code in HTTP_UNAVAILABLE_CODES:
                    with self.subTest(stage=stage, main=main_code, dev=dev_code):
                        save_json(self.repos_path, self.initial_repos)
                        self.summary.reset_mock()
                        self.fetch_hash.side_effect = (
                            get_hash if stage == "hash" else None
                        )
                        for branch, code in (("main", main_code), ("dev", dev_code)):
                            url = self.url(branch, "patches-bundle.json")
                            self.responses[url] = self.http_error(url, code)
                        with patch.object(
                            bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES
                        ):
                            bundle_fetch.fetch_all_repos()
                        self.summary.assert_called_once()
                        summary = self.summary.call_args.args[0]
                        self.assertIn("### Bundle metadata (1)", summary)
                        self.assertEqual(summary.count("- https://"), 1)
                        if main_code == dev_code:
                            self.assertNotIn("(main)", summary)
                            self.assertNotIn("(dev)", summary)
                            self.assertIn(f"Request failed (HTTP {main_code})", summary)
                        else:
                            self.assertIn(
                                "https://github.com/owner/alpha: "
                                f"(main) Request failed (HTTP {main_code}); "
                                f"(dev) Request failed (HTTP {dev_code})",
                                summary,
                            )
                        self.assertNotIn("HTTP 404/451", summary)
                        updated_repo = load_json(self.repos_path)[
                            "https://github.com/owner/alpha"
                        ]
                        for branch in DEFAULT_BRANCHES:
                            self.assertIsNone(updated_repo[branch])

    def test_single_unavailable_metadata_branch_is_suppressed_in_summary(self) -> None:
        for other_failure in (None, TimeoutError("Timed out")):
            with self.subTest(other_failure=other_failure):
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
                    self.assertIn(
                        "owner/alpha: (main) Request failed (HTTP 404); "
                        "(dev) Request failed: Timed out",
                        summary,
                    )
                    self.assertIn("Timed out", summary)
                    self.assertNotIn("404/451", summary)
                else:
                    self.assertEqual(
                        self.summary.call_args.args[0], "## 📥 Fetch (1/1):"
                    )

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
            self.assertFalse(any(bundle_fetch.collect_fetch_errors(results).values()))
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
        self.assertEqual(
            errors["metadata"],
            ["https://gitlab.com/owner/alpha: Request failed (HTTP 404)"],
        )
        self.assertEqual(sum(len(messages) for messages in errors.values()), 1)

    def test_mpp_failures_are_reported_when_other_metadata_branch_is_missing(
        self,
    ) -> None:
        for failure in (
            self.http_error(self.bundle_data["download_url"], 404),
            self.http_error(self.bundle_data["download_url"], 451),
        ):
            with self.subTest(failure=str(failure)):
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
                self.assertIn("owner/alpha: (main)", summary)
                self.assertIn("Bundle metadata (1)", summary)
                self.assertIn("Bundle download (1)", summary)
                self.assertIn(f"(main) Request failed (HTTP {failure.code})", summary)
                self.assertIn("(dev) Request failed (HTTP 404)", summary)
                self.assertNotIn("on main and dev", summary)

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
        self.assertEqual(summary.count("- https://"), 2)
        self.assertIn("Bundle image (1)", summary)
        self.assertIn("Request failed: Image timeout", summary)

    def test_identical_bundle_failures_have_one_entry_without_branches(self) -> None:
        self.responses[self.bundle_data["download_url"]] = self.http_error(
            self.bundle_data["download_url"], 503
        )
        with patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES):
            bundle_fetch.fetch_all_repos()
        summary = self.summary.call_args.args[0]
        self.assertIn("Bundle download (1)", summary)
        self.assertIn(
            "https://github.com/owner/alpha: Request failed (HTTP 503)", summary
        )
        self.assertEqual(summary.count("- https://"), 1)
        self.assertNotIn("(main)", summary)
        self.assertNotIn("(dev)", summary)
        self.assertNotIn(self.bundle_data["download_url"], summary)
        self.assertEqual(load_json(self.repos_path), self.initial_repos)
        self.assertTrue(summary.startswith("## 📥 Fetch (0/1):"))
        self.assertEqual(
            self.fetch_request.call_args_list.count(
                call(self.bundle_data["download_url"], binary=True)
            ),
            1,
        )
        for branch in DEFAULT_BRANCHES:
            self.assertNotIn(
                call(self.url(branch, "patches-list.json"), binary=True),
                self.fetch_request.call_args_list,
            )

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
        self.assertIn("Bundle metadata (1)", summary)
        self.assertIn("Bundle download (1)", summary)
        self.assertIn("(main) Request failed (HTTP 403)", summary)
        self.assertIn("(dev) Request failed (HTTP 403)", summary)
        self.assertEqual(summary.count("- https://"), len(DEFAULT_BRANCHES))
        self.assertEqual(summary.count("<details>"), 1)
        details_content, remaining_content = summary.split("</details>")
        self.assertIn("(main) Request failed (HTTP 403)", details_content)
        self.assertNotIn("(dev) Request failed (HTTP 403)", details_content)
        self.assertIn("(dev) Request failed (HTTP 403)", remaining_content)

    def test_branch_errors_are_suppressed_when_the_other_branch_succeeds(self) -> None:
        for category in ("metadata", "bundle", "patch_list"):
            with self.subTest(category=category):
                results = [
                    bundle_fetch.BranchFetchResult(
                        "github",
                        "owner/alpha",
                        "main",
                        "main-old",
                        error_category=category,
                        error_message="Request failed (HTTP 503)",
                    ),
                    bundle_fetch.BranchFetchResult(
                        "github", "owner/alpha", "dev", "dev-new"
                    ),
                ]
                with patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES):
                    self.assertFalse(
                        any(bundle_fetch.collect_fetch_errors(results).values())
                    )

    def test_patch_list_request_errors_do_not_trigger_parsing(self) -> None:
        for code in (403, 451):
            with self.subTest(code=code):
                self.summary.reset_mock()
                for branch in DEFAULT_BRANCHES:
                    url = self.url(branch, "patches-list.json")
                    self.responses[url] = self.http_error(url, code)
                with patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES):
                    bundle_fetch.fetch_all_repos()
                summary = self.summary.call_args.args[0]
                self.assertIn("Patch list (1)", summary)
                self.assertIn(f"Request failed (HTTP {code})", summary)
                self.assertNotIn("Bundle metadata", summary)
                self.assertNotIn("Bundle download", summary)
                self.run_process.assert_not_called()
                self.assertEqual(load_json(self.repos_path), self.initial_repos)

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
        self.assertIn("Patch list (1)", summary)
        self.assertIn(
            "https://github.com/owner/alpha: Failed to generate `patches-list.json`",
            summary,
        )
        self.assertNotIn("HTTP 404", summary)
        self.assertTrue(summary.startswith("## 📥 Fetch (0/1):"))
        self.assertEqual(summary.count("- https://"), 1)
        self.run_process.assert_called_once()
        for branch in DEFAULT_BRANCHES:
            self.assertIsNone(
                load_json(self.repos_path)["https://github.com/owner/alpha"][branch]
            )

    def test_missing_or_blocked_image_is_cleared_without_warning(self) -> None:
        image_url = self.url("main", "patches-bundle.png")
        for code in HTTP_UNAVAILABLE_CODES:
            with (
                self.subTest(code=code),
                patch.object(
                    bundle_fetch,
                    "get_image_sha",
                    side_effect=self.http_error(image_url, code),
                ),
            ):
                self.assertEqual(
                    bundle_fetch.process_image("github", "owner/alpha", "image-old"),
                    ("github", "owner/alpha", None, True, None),
                )
                self.assertEqual(
                    bundle_fetch.process_image("github", "owner/alpha", None),
                    ("github", "owner/alpha", None, False, None),
                )

    def test_unavailable_metadata_and_mpp_clear_sha_without_deleting_files(
        self,
    ) -> None:
        original_responses = self.responses.copy()
        for stage in ("hash", "metadata", "mpp"):
            for code in HTTP_UNAVAILABLE_CODES:
                with self.subTest(stage=stage, code=code):
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
                    self.assertIsNone(
                        load_json(self.repos_path)["https://github.com/owner/alpha"][
                            "main"
                        ]
                    )
                    for path, content in old_contents.items():
                        self.assertEqual(path.read_bytes(), content)
                    self.run_process.assert_not_called()

    def test_invalid_metadata_clears_target(self) -> None:
        invalid_metadata = [
            b"{broken",
            b"[]",
            b"{}",
            json.dumps(
                {"download_url": "https://github.com/other/repo/bundle.mpp"}
            ).encode(),
        ]
        for content in invalid_metadata:
            with self.subTest(metadata=content):
                self.responses[self.url("main", "patches-bundle.json")] = content
                result = bundle_fetch.process_repo_branch(
                    "github", "owner/alpha", "main", "main-old"
                )
                self.assertIsNone(result.new_sha)
                self.assertFalse(result.needs_parse)
                self.assertTrue(result.error_message)
                self.assertEqual(result.error_category, "metadata")
                self.assertIn(
                    result.error_message, ("Invalid data", "Invalid `download_url`")
                )

    def test_unreadable_or_missing_manifest_name_keeps_existing_display_name(
        self,
    ) -> None:
        contents = [b"not a zip archive"]
        for manifest in (None, b"Version: 1.0\n", b"Name: \n", b"Name: \xff\n"):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                if manifest is not None:
                    archive.writestr("META-INF/MANIFEST.MF", manifest)
            contents.append(buffer.getvalue())
        for content in contents:
            with self.subTest(content=content):
                save_json(self.repos_path, self.initial_repos)
                self.responses[self.bundle_data["download_url"]] = content
                bundle_fetch.fetch_all_repos()
                updated_repo = load_json(self.repos_path)[
                    "https://github.com/owner/alpha"
                ]
                self.assertEqual(updated_repo["name"], "Alpha old")
                self.assertEqual(updated_repo["main"], "main-new")
                self.assertEqual(
                    (self.mpp_dir / "github~owner~alpha~main.mpp").read_bytes(),
                    content,
                )
                self.assertEqual(self.summary.call_args.args[0], "## 📥 Fetch (1/1):")
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
        self.assertEqual(updated_repo["name"], "Alpha new")
        self.assertEqual(updated_repo["main"], "main-new")
        self.assertEqual(self.summary.call_args.args[0], "## 📥 Fetch (1/1):")
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
        self.assertEqual(
            load_json(self.bundles_dir / f"{result.target_name}.json"),
            {"download_url": rewritten_url},
        )
        self.assertEqual(result.bundle_name, "Alpha new")
        self.assertFalse(result.needs_parse)

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
        self.assertIsNone(
            load_json(self.repos_path)["https://github.com/owner/alpha"]["main"]
        )
        self.assertTrue((self.patches_dir / "github~owner~alpha~main.json").exists())
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
        self.assertEqual(result.new_sha, "main-old")
        self.assertFalse(result.status_changed)
        self.fetch_request.assert_not_called()

    def test_image_updates_are_independent_of_branch_failures(self) -> None:
        self.fetch_hash.side_effect = self.http_error(
            self.url("main", "patches-bundle.json"), HTTP_NOT_FOUND
        )
        for mode in ("daily", "weekly"):
            with (
                self.subTest(mode=mode),
                patch.object(bundle_fetch, "get_image_sha", return_value="image-new"),
            ):
                bundle_fetch.fetch_all_repos(**{mode: True})
                updated_repo = load_json(self.repos_path)[
                    "https://github.com/owner/alpha"
                ]
                self.assertEqual(updated_repo["image"], "image-new")
                self.assertIsNone(updated_repo["main"])
                self.assertEqual(updated_repo["name"], "Alpha old")

    def test_file_write_failure_stops_fetch(self) -> None:
        with (
            patch.object(
                bundle_fetch, "save_json", side_effect=PermissionError("Cannot write")
            ),
            self.assertRaises(PermissionError),
        ):
            bundle_fetch.fetch_all_repos()
        self.assertEqual(load_json(self.repos_path), self.initial_repos)

    def test_missing_hash_header_is_not_a_missing_file(self) -> None:
        with patch.object(bundle_fetch.urllib.request, "urlopen") as open_url:
            open_url.return_value.__enter__.return_value.getheader.return_value = None
            with self.assertRaisesRegex(ValueError, "Missing `ETag`"):
                bundle_fetch.get_remote_file_hash(
                    self.url("main", "patches-bundle.json"), "github"
                )

    def test_hash_request_preserves_http_errors_for_the_caller(self) -> None:
        url = self.url("main", "patches-bundle.json")
        for code in HTTP_UNAVAILABLE_CODES:
            with (
                self.subTest(code=code),
                patch.object(
                    bundle_fetch.urllib.request,
                    "urlopen",
                    side_effect=self.http_error(url, code),
                ),
            ):
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    bundle_fetch.get_remote_file_hash(url, "github")
                self.assertEqual(raised.exception.code, code)

    def test_parser_failure_stops_before_saving_repos(self) -> None:
        patch_url = self.url("main", "patches-list.json")
        self.responses[patch_url] = self.http_error(patch_url, HTTP_NOT_FOUND)
        self.run_process.side_effect = OSError("Cannot launch parser")
        with self.assertRaises(OSError):
            bundle_fetch.fetch_all_repos()
        self.assertEqual(load_json(self.repos_path), self.initial_repos)

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
            self.assertFalse(self.parsed_path.exists())
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
        self.assertEqual(updated_repo["main"], "main-new")
        self.assertIsNone(updated_repo["dev"])
        self.assertEqual(updated_repo["name"], "Alpha new")
        self.assertEqual(
            sum(
                arguments.args[0] == self.repos_path
                for arguments in save.call_args_list
            ),
            1,
        )
        self.run_process.assert_called_once()
        self.assertEqual(self.summary.call_args.args[0], "## 📥 Fetch (1/1):")

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
        self.assertTrue(summary.startswith("## 📥 Fetch (1/3):"))
        self.assertIn("Bundle image (3)", summary)
        self.assertEqual(load_json(self.repos_path), repos)

    def test_empty_repository_list_still_reports_zero_counts(self) -> None:
        save_json(self.repos_path, {})
        bundle_fetch.fetch_all_repos()
        self.assertEqual(self.summary.call_args.args[0], "## 📥 Fetch (0/0):")
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
        self.assertEqual(
            load_json(self.repos_path)["https://github.com/owner/alpha"]["name"],
            "main name",
        )

    def test_dev_update_downloads_bundle_but_keeps_existing_main_name(self) -> None:
        self.seed_target()
        save_json(self.bundles_dir / "github~owner~alpha~main.json", self.bundle_data)
        self.fetch_hash.side_effect = lambda _source, _repo, branch: (
            "main-old" if branch == "main" else "dev-new"
        )
        with patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES):
            bundle_fetch.fetch_all_repos()
        self.assertEqual(
            load_json(self.repos_path)["https://github.com/owner/alpha"]["name"],
            "Alpha old",
        )
        self.fetch_request.assert_any_call(
            self.url("dev", "patches-list.json"), binary=True
        )
        self.assertTrue((self.mpp_dir / "github~owner~alpha~dev.mpp").is_file())

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
        self.assertEqual(
            load_json(self.repos_path)["https://github.com/owner/alpha"]["name"],
            "Alpha new",
        )
        self.fetch_request.assert_called_once_with(
            self.bundle_data["download_url"], binary=True
        )

    def test_new_empty_repository_entry_is_fetched(self) -> None:
        save_json(self.repos_path, {"https://github.com/owner/alpha": {}})
        bundle_fetch.fetch_all_repos()
        self.assertEqual(
            load_json(self.repos_path)["https://github.com/owner/alpha"]["main"],
            "main-new",
        )
        self.assertEqual(
            load_json(self.repos_path)["https://github.com/owner/alpha"]["name"],
            "Alpha new",
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
        self.assertEqual(result.new_sha, "main-new")
        self.assertIsNone(result.error_message)


class RepositoryMetadataRefreshTests(unittest.TestCase):
    def setUp(self) -> None:
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
            self.assertEqual(bundle_fetch.refresh_repo_metadata(repos, False), [])
            request.assert_not_called()
            repos[self.url].pop("stars")
            bundle_fetch.refresh_repo_metadata(repos, False)
            request.assert_called_once_with(self.url)
        self.assertEqual(repos[self.url]["stars"], 23)

    def test_request_errors_preserve_all_metadata_and_pending_rename(self) -> None:
        self.metadata["renamedTo"] = "https://github.com/owner/new"
        for reason in (
            "Request failed (HTTP 404)",
            "Request failed (HTTP 451)",
            "Request failed: timed out",
        ):
            with (
                self.subTest(reason=reason),
                patch.object(
                    bundle_fetch, "fetch_repo_details", return_value={"error": reason}
                ),
            ):
                repos = {self.url: dict(self.metadata)}
                self.assertEqual(
                    bundle_fetch.refresh_repo_metadata(repos, True),
                    [f"{self.url}: {reason}"],
                )
                self.assertEqual(repos[self.url], self.metadata)

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
        self.assertNotIn("isArchived", repos[self.url])
        self.assertEqual(repos[self.url]["renamedTo"], "https://github.com/owner/new")
        self.assertEqual(set(repos), {self.url})
        self.assertIn("Renamed to", warnings[0])
        with patch.object(
            bundle_fetch,
            "fetch_repo_details",
            return_value={"full_name": "OWNER/ALPHA", "is_archived": True},
        ):
            warnings = bundle_fetch.refresh_repo_metadata(repos, True)
        self.assertNotIn("renamedTo", repos[self.url])
        self.assertTrue(repos[self.url]["isArchived"])
        self.assertIn("Repository is archived", warnings[0])

    def test_null_hashes_do_not_trigger_repository_request(self) -> None:
        with patch.object(bundle_fetch, "fetch_repo_details") as request:
            self.assertEqual(
                bundle_fetch.refresh_repo_metadata({self.url: {}}, True), []
            )
            request.assert_not_called()

    def test_fetch_persists_metadata_once_and_defers_custom_source_changes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
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
                self.assertEqual(kwargs["renamed_repo"], "owner/new")
                return bundle_fetch.BranchFetchResult(source, repo, branch, current_sha)

            with (
                patch.multiple(
                    bundle_fetch,
                    REPOS_JSON_PATH=repos_path,
                    BUNDLES_DIR=root / "bundles",
                    PATCHES_DIR=root / "patches",
                    MPP_DIR=root / "mpp",
                ),
                patch.object(
                    bundle_fetch, "process_repo_branch", side_effect=unchanged
                ),
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
                self.assertIn("Repository metadata (1)", summary.call_args.args[0])
            metadata = load_json(repos_path)[self.url]
            self.assertEqual(metadata["renamedTo"], "https://github.com/owner/new")
            self.assertEqual(metadata["main"], "sha")
            self.assertEqual(metadata["stars"], 23)
            self.assertEqual(custom_path.read_bytes(), custom_before)


if __name__ == "__main__":
    unittest.main()
