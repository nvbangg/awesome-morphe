import io
import json
import tempfile
import threading
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import call, patch

import fetch as bundle_fetch
from utils import (
    DEFAULT_BRANCHES,
    UNAVAILABLE_HTTP_CODES,
    build_raw_url,
    load_json,
    load_lines,
    save_json,
)

PATCH_LIST_BARRIER_TIMEOUT_SECONDS = 5


class BundleFetchTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.root = Path(temporary_directory.name)
        self.bundles_dir = self.root / "bundles"
        self.patches_dir = self.root / "patches"
        self.mpp_dir = self.root / "mpp"
        self.repos_path = self.root / "repos.json"
        self.pending_path = self.root / "pending_repos.json"
        self.updated_path = self.root / "updated_files.txt"
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
        with zipfile.ZipFile(mpp_buffer, "w") as mpp_file:
            mpp_file.writestr("META-INF/MANIFEST.MF", "Name: Alpha new\n")
        self.mpp_bytes = mpp_buffer.getvalue()
        self.responses = {self.bundle_data["download_url"]: self.mpp_bytes}
        for branch in DEFAULT_BRANCHES:
            self.responses[
                build_raw_url("github", "owner/alpha", branch, "patches-bundle.json")
            ] = json.dumps(self.bundle_data)
            self.responses[
                build_raw_url("github", "owner/alpha", branch, "patches-list.json")
            ] = json.dumps(self.patches_data)

        path_patcher = patch.multiple(
            bundle_fetch,
            BUNDLES_DIR=self.bundles_dir,
            PATCHES_DIR=self.patches_dir,
            MPP_DIR=self.mpp_dir,
            REPOS_JSON_PATH=self.repos_path,
            PENDING_REPOS_PATH=self.pending_path,
            UPDATED_FILES_PATH=self.updated_path,
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
        summary_patcher = patch.object(bundle_fetch, "append_step_summary")
        self.summary = summary_patcher.start()
        self.addCleanup(summary_patcher.stop)

    def download(self, url: str, binary: bool = False) -> str | bytes:
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        self.assertIsInstance(response, bytes if binary else str)
        return response

    def test_patch_lists_download_concurrently_and_keep_targets_separate(self) -> None:
        barrier = threading.Barrier(len(DEFAULT_BRANCHES))
        patch_urls = {
            build_raw_url("github", "owner/alpha", branch, "patches-list.json")
            for branch in DEFAULT_BRANCHES
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
        self.assertEqual(
            load_json(self.pending_path),
            {
                "owner/alpha": {
                    "name": "Alpha new",
                    "github": {branch: f"{branch}-new" for branch in DEFAULT_BRANCHES},
                }
            },
        )
        self.assertFalse(self.updated_path.exists())
        self.assertEqual(load_json(self.repos_path), self.initial_repos)

    def test_patch_list_failures_queue_downloaded_mpp_for_parsing(self) -> None:
        patch_url = build_raw_url("github", "owner/alpha", "main", "patches-list.json")
        failures = [
            urllib.error.HTTPError(
                patch_url, UNAVAILABLE_HTTP_CODES[0], "Not found", None, None
            ),
            TimeoutError("Patch list timeout"),
            "{broken",
        ]
        for failure in failures:
            with self.subTest(failure=failure):
                if isinstance(failure, urllib.error.HTTPError):
                    self.addCleanup(failure.close)
                self.responses[patch_url] = failure

                bundle_fetch.fetch_all_repos()

                self.assertEqual(
                    load_lines(self.updated_path), ["mpp/github~owner~alpha~main.mpp"]
                )
                self.assertEqual(
                    load_json(self.pending_path),
                    {
                        "owner/alpha": {
                            "name": "Alpha new",
                            "github": {"main": "main-new"},
                        }
                    },
                )
                self.assertFalse(
                    (self.patches_dir / "github~owner~alpha~main.json").exists()
                )
                self.assertEqual(load_json(self.repos_path), self.initial_repos)

    def test_unchanged_target_skips_downloads(self) -> None:
        save_json(self.bundles_dir / "github~owner~alpha~main.json", self.bundle_data)
        save_json(self.patches_dir / "github~owner~alpha~main.json", self.patches_data)
        self.fetch_hash.return_value = "main-old"

        bundle_fetch.fetch_all_repos()

        self.fetch_request.assert_not_called()
        self.assertEqual(load_json(self.pending_path), {})
        self.assertFalse(self.updated_path.exists())

    def test_transient_errors_preserve_current_sha_without_queuing(self) -> None:
        bundle_url = build_raw_url(
            "github", "owner/alpha", "main", "patches-bundle.json"
        )
        original_responses = self.responses.copy()
        for stage in ("hash", "bundle", "mpp"):
            with self.subTest(stage=stage):
                self.responses = original_responses.copy()
                self.fetch_hash.side_effect = None
                failure = TimeoutError(f"{stage} timeout")
                if stage == "hash":
                    self.fetch_hash.side_effect = failure
                else:
                    self.responses[
                        bundle_url
                        if stage == "bundle"
                        else self.bundle_data["download_url"]
                    ] = failure

                result = bundle_fetch.process_repo_branch(
                    "github", "owner/alpha", "main", "main-old"
                )

                self.assertEqual(result.new_sha, "main-old")
                self.assertFalse(result.status_changed)
                self.assertFalse(result.needs_parse)
                self.assertIn(str(failure), result.error_message)
                self.assertFalse(
                    (self.bundles_dir / "github~owner~alpha~main.json").exists()
                )

    def test_unavailable_targets_do_not_queue_patch_list_downloads(self) -> None:
        bundle_url = build_raw_url(
            "github", "owner/alpha", "main", "patches-bundle.json"
        )
        original_responses = self.responses.copy()
        for stage in ("hash", "bundle", "mpp", "invalid_url"):
            with self.subTest(stage=stage):
                self.responses = original_responses.copy()
                self.fetch_request.reset_mock()
                self.fetch_hash.return_value = None if stage == "hash" else "main-new"
                if stage in ("bundle", "mpp"):
                    url = (
                        bundle_url
                        if stage == "bundle"
                        else self.bundle_data["download_url"]
                    )
                    self.responses[url] = urllib.error.HTTPError(
                        url, UNAVAILABLE_HTTP_CODES[0], "Not found", None, None
                    )
                    self.addCleanup(self.responses[url].close)
                elif stage == "invalid_url":
                    self.responses[bundle_url] = json.dumps(
                        {
                            "download_url": "https://github.com/other/repo/releases/download/latest/bundle.mpp"
                        }
                    )

                bundle_fetch.fetch_all_repos()

                expected_sha = None if stage == "hash" else "main-new"
                self.assertEqual(
                    load_json(self.pending_path),
                    {"owner/alpha": {"github": {"main": expected_sha}}},
                )
                self.assertFalse(self.updated_path.exists())
                self.assertFalse(
                    (self.bundles_dir / "github~owner~alpha~main.json").exists()
                )
                patch_url = build_raw_url(
                    "github", "owner/alpha", "main", "patches-list.json"
                )
                self.assertNotIn(call(patch_url), self.fetch_request.call_args_list)

    def test_gitlab_worker_saves_rewritten_download_url_and_patch_list(self) -> None:
        bundle_url = build_raw_url(
            "gitlab", "owner/alpha", "main", "patches-bundle.json"
        )
        patch_url = build_raw_url("gitlab", "owner/alpha", "main", "patches-list.json")
        numeric_mpp_url = "https://gitlab.com/api/v4/projects/123/packages/generic/bundle/latest/bundle.mpp"
        rewritten_mpp_url = numeric_mpp_url.replace("/123/", "/owner%2Falpha/")
        self.responses[bundle_url] = json.dumps({"download_url": numeric_mpp_url})
        self.responses[rewritten_mpp_url] = self.mpp_bytes
        self.responses[patch_url] = json.dumps(self.patches_data)

        result = bundle_fetch.process_repo_branch(
            "gitlab", "owner/alpha", "main", "main-old"
        )

        self.assertEqual(
            load_json(self.bundles_dir / "gitlab~owner~alpha~main.json"),
            {"download_url": rewritten_mpp_url},
        )
        self.assertEqual(
            load_json(self.patches_dir / "gitlab~owner~alpha~main.json"),
            self.patches_data,
        )
        self.assertTrue(result.status_changed)
        self.assertFalse(result.needs_parse)
        self.assertEqual(result.new_sha, "main-new")
        self.assertEqual(result.bundle_name, "Alpha new")
        self.fetch_request.assert_any_call(rewritten_mpp_url, binary=True)

    def test_weekly_unavailable_mpp_still_cleans_existing_target(self) -> None:
        save_json(self.bundles_dir / "github~owner~alpha~main.json", self.bundle_data)
        save_json(self.patches_dir / "github~owner~alpha~main.json", self.patches_data)
        self.mpp_dir.mkdir()
        (self.mpp_dir / "github~owner~alpha~main.mpp").write_bytes(self.mpp_bytes)
        self.fetch_hash.return_value = "main-old"

        with patch.object(bundle_fetch, "get_remote_file_hash", return_value=None):
            result = bundle_fetch.process_repo_branch(
                "github", "owner/alpha", "main", "main-old", weekly=True
            )

        self.assertTrue(result.status_changed)
        self.assertFalse(result.needs_parse)
        self.assertEqual(result.new_sha, "main-old")
        self.assertEqual(list(self.bundles_dir.iterdir()), [])
        self.assertEqual(list(self.patches_dir.iterdir()), [])
        self.assertEqual(list(self.mpp_dir.iterdir()), [])
        self.fetch_request.assert_not_called()

    def test_daily_and_weekly_keep_image_updates_in_pending(self) -> None:
        for mode in ("daily", "weekly"):
            with (
                self.subTest(mode=mode),
                patch.object(bundle_fetch, "get_image_sha", return_value="image-new"),
            ):
                bundle_fetch.fetch_all_repos(**{mode: True})

                self.assertEqual(
                    load_json(self.pending_path),
                    {
                        "owner/alpha": {
                            "name": "Alpha new",
                            "github": {"main": "main-new", "image": "image-new"},
                        }
                    },
                )
                self.assertEqual(load_json(self.repos_path), self.initial_repos)


if __name__ == "__main__":
    unittest.main()
