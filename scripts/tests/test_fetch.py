import io
import json
import tempfile
import threading
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

import fetch as bundle_fetch
from utils import DEFAULT_BRANCHES, build_raw_url, load_json, save_json

PATCH_LIST_BARRIER_TIMEOUT_SECONDS = 5
HTTP_NOT_FOUND = 404
HTTP_UNAVAILABLE_CODES = (404, 451)
HTTP_OTHER_CODES = (403, 429, 500, 503)


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
            "owner/alpha": {
                "name": "Alpha old",
                "github": {"main": "main-old", "dev": "dev-old", "image": "image-old"},
            }
        }
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
        hash_patcher = patch.object(
            bundle_fetch, "get_file_sha", return_value="main-new"
        )
        self.fetch_hash = hash_patcher.start()
        self.addCleanup(hash_patcher.stop)
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
        updated_repo = load_json(self.repos_path)["owner/alpha"]
        self.assertEqual(updated_repo["name"], "Alpha new")
        for branch in DEFAULT_BRANCHES:
            self.assertEqual(updated_repo["github"][branch], f"{branch}-new")
        self.assertFalse(self.updated_path.exists())
        self.run_process.assert_not_called()

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
                    load_json(self.repos_path)["owner/alpha"]["github"]["main"],
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

    def test_missing_json_refetches_even_with_unchanged_hash(self) -> None:
        self.fetch_hash.return_value = "main-old"
        bundle_fetch.fetch_all_repos()
        self.assertEqual(
            load_json(self.patches_dir / "github~owner~alpha~main.json"),
            self.patches_data,
        )
        self.assertEqual(self.fetch_request.call_count, 3)

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
                    self.assertIn("owner/alpha (main)", self.summary.call_args.args[0])

    def test_both_unavailable_metadata_branches_have_one_summary_entry(self) -> None:
        for stage in ("hash", "metadata"):
            for main_code in HTTP_UNAVAILABLE_CODES:
                for dev_code in HTTP_UNAVAILABLE_CODES:
                    with self.subTest(stage=stage, main=main_code, dev=dev_code):
                        save_json(self.repos_path, self.initial_repos)
                        self.summary.reset_mock()
                        self.fetch_hash.return_value = (
                            None if stage == "hash" else "main-new"
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
                        self.assertEqual(summary.count("- https://"), 1)
                        self.assertIn("on main and dev (HTTP 404/451)", summary)
                        updated_repo = load_json(self.repos_path)["owner/alpha"]
                        for branch in DEFAULT_BRANCHES:
                            self.assertIsNone(updated_repo["github"][branch])

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
                        return None
                    if failure:
                        raise failure
                    return "dev-new"

                self.fetch_hash.side_effect = get_hash
                with patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES):
                    bundle_fetch.fetch_all_repos()
                if other_failure:
                    self.summary.assert_called_once()
                    summary = self.summary.call_args.args[0]
                    self.assertIn("owner/alpha (dev)", summary)
                    self.assertIn("Timed out", summary)
                    self.assertNotIn("404/451", summary)
                else:
                    self.summary.assert_not_called()

    def test_missing_metadata_is_grouped_by_source_and_repository(self) -> None:
        results = [
            bundle_fetch.BranchFetchResult(
                source, repo, branch, None, metadata_unavailable=True
            )
            for source, repo, branch in (
                ("github", "owner/alpha", "main"),
                ("gitlab", "owner/alpha", "dev"),
                ("github", "owner/beta", "dev"),
            )
        ]
        with patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES):
            self.assertEqual(bundle_fetch.collect_fetch_errors(results), [])
            results.append(
                bundle_fetch.BranchFetchResult(
                    "gitlab", "owner/alpha", "main", None, metadata_unavailable=True
                )
            )
            errors = bundle_fetch.collect_fetch_errors(results)
        self.assertEqual(len(errors), 1)
        self.assertIn("https://gitlab.com/owner/alpha:", errors[0])

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
                self.fetch_hash.side_effect = lambda _source, _repo, branch: (
                    "main-new" if branch == "main" else None
                )
                self.responses[self.bundle_data["download_url"]] = failure
                with patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES):
                    bundle_fetch.fetch_all_repos()
                summary = self.summary.call_args.args[0]
                self.assertIn("owner/alpha (main)", summary)
                self.assertIn(".mpp", summary)
                self.assertNotIn("on main and dev", summary)

    def test_image_failure_is_reported_without_repeating_missing_metadata(self) -> None:
        self.fetch_hash.return_value = None
        with (
            patch.object(bundle_fetch, "DEFAULT_BRANCHES", DEFAULT_BRANCHES),
            patch.object(
                bundle_fetch, "get_image_sha", side_effect=TimeoutError("Image timeout")
            ),
        ):
            bundle_fetch.fetch_all_repos(daily=True)
        summary = self.summary.call_args.args[0]
        self.assertEqual(summary.count("- https://"), 2)
        self.assertIn("Failed to fetch image: Image timeout", summary)

    def test_unavailable_metadata_and_mpp_clear_sha_without_deleting_files(
        self,
    ) -> None:
        original_responses = self.responses.copy()
        for stage in ("hash", "metadata", "mpp"):
            for code in HTTP_UNAVAILABLE_CODES:
                with self.subTest(stage=stage, code=code):
                    save_json(self.repos_path, self.initial_repos)
                    self.responses = original_responses.copy()
                    self.fetch_hash.return_value = (
                        None if stage == "hash" else "main-new"
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
                        load_json(self.repos_path)["owner/alpha"]["github"]["main"]
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
                updated_repo = load_json(self.repos_path)["owner/alpha"]
                self.assertEqual(updated_repo["name"], "Alpha old")
                self.assertEqual(updated_repo["github"]["main"], "main-new")
                self.assertEqual(
                    (self.mpp_dir / "github~owner~alpha~main.mpp").read_bytes(),
                    content,
                )
                self.summary.assert_not_called()
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
        updated_repo = load_json(self.repos_path)["owner/alpha"]
        self.assertEqual(updated_repo["name"], "Alpha new")
        self.assertEqual(updated_repo["github"]["main"], "main-new")
        self.summary.assert_not_called()
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
        with patch.object(bundle_fetch, "get_remote_file_hash", return_value=None):
            bundle_fetch.fetch_all_repos(weekly=True)
        self.assertIsNone(load_json(self.repos_path)["owner/alpha"]["github"]["main"])
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
        self.fetch_hash.return_value = None
        for mode in ("daily", "weekly"):
            with (
                self.subTest(mode=mode),
                patch.object(bundle_fetch, "get_image_sha", return_value="image-new"),
            ):
                bundle_fetch.fetch_all_repos(**{mode: True})
                updated_repo = load_json(self.repos_path)["owner/alpha"]
                self.assertEqual(updated_repo["github"]["image"], "image-new")
                self.assertIsNone(updated_repo["github"]["main"])
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
            with self.assertRaisesRegex(ValueError, "Missing ETag"):
                bundle_fetch.get_remote_file_hash(
                    self.url("main", "patches-bundle.json"), "github"
                )

    def test_metadata_head_404_and_451_mean_unavailable(self) -> None:
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
                self.assertIsNone(bundle_fetch.get_remote_file_hash(url, "github"))

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
        updated_repo = load_json(self.repos_path)["owner/alpha"]
        self.assertEqual(updated_repo["github"]["main"], "main-new")
        self.assertIsNone(updated_repo["github"]["dev"])
        self.assertEqual(updated_repo["name"], "Alpha new")
        self.assertEqual(
            sum(
                arguments.args[0] == self.repos_path
                for arguments in save.call_args_list
            ),
            1,
        )
        self.run_process.assert_called_once()
        summary = self.summary.call_args.args[0]
        self.assertIn("owner/alpha (dev): Parser did not produce", summary)
        self.assertNotIn("owner/alpha (main)", summary)


if __name__ == "__main__":
    unittest.main()
