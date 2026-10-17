import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import update as bundle_update
from updater import gplay_scrape, local_parse, repo_info
from utils import PACKAGE_UNIVERSAL, load_json, save_json

CURRENT_TIME_SECONDS = 1_800_000_000
BUNDLE_TIME_MS = 1_700_000_000_000
FIRST_SEEN_MS = 1_600_000_000_000


class BundleUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.root = Path(temporary_directory.name)
        self.bundles_dir = self.root / "bundles"
        self.patches_dir = self.root / "patches"
        self.repos_path = self.root / "repos.json"
        self.public_path = self.root / "catalog.json"
        self.hashes_path = self.root / "hashes.json"
        self.history_path = self.root / "history.json"
        self.custom_path = self.root / "custom.json"
        self.official_path = self.root / "official.json"
        self.state_paths = [
            self.repos_path,
            self.public_path,
            self.hashes_path,
            self.history_path,
            self.custom_path,
        ]
        for path in [*self.state_paths, self.official_path]:
            save_json(path, {})
        path_patcher = patch.multiple(
            bundle_update,
            REPOS_JSON_PATH=self.repos_path,
            BUNDLES_JSON_PATH=self.public_path,
            HASHES_PATH=self.hashes_path,
            HISTORY_PATH=self.history_path,
            CUSTOM_JSON_PATH=self.custom_path,
            OFFICIAL_BUNDLES_PATH=self.official_path,
        )
        path_patcher.start()
        self.addCleanup(path_patcher.stop)
        local_patcher = patch.multiple(
            local_parse, BUNDLES_DIR=self.bundles_dir, PATCHES_DIR=self.patches_dir
        )
        local_patcher.start()
        self.addCleanup(local_patcher.stop)
        official_patcher = patch.object(
            gplay_scrape, "OFFICIAL_BUNDLES_PATH", self.official_path
        )
        official_patcher.start()
        self.addCleanup(official_patcher.stop)
        repo_patcher = patch.object(
            repo_info,
            "fetch_repo_details",
            return_value={
                "stars": 7,
                "description": "Repository",
                "avatar_url": "https://example.com/avatar.png",
            },
        )
        self.fetch_repo = repo_patcher.start()
        self.addCleanup(repo_patcher.stop)
        app_patcher = patch.object(
            gplay_scrape, "fetch_app_details", return_value=(None, False)
        )
        self.fetch_app = app_patcher.start()
        self.addCleanup(app_patcher.stop)
        summary_patcher = patch.object(bundle_update, "append_step_summary")
        self.summary = summary_patcher.start()
        self.addCleanup(summary_patcher.stop)
        network_patcher = patch(
            "urllib.request.urlopen",
            side_effect=AssertionError("Unexpected network access"),
        )
        network_patcher.start()
        self.addCleanup(network_patcher.stop)

    def add_target(
        self,
        repo: str = "owner/alpha",
        source: str = "github",
        branch: str = "main",
        timestamp: int = BUNDLE_TIME_MS,
        patches: list | None = None,
        sha: str | None = "downloaded-sha",
    ) -> Path:
        repos = load_json(self.repos_path)
        entry = repos.setdefault(repo, {})
        entry.setdefault(source, {"main": None, "dev": None})[branch] = sha
        save_json(self.repos_path, repos)
        prefix = f"{source}~{repo.replace('/', '~')}~{branch}"
        save_json(
            self.bundles_dir / f"{prefix}.json",
            {
                "download_url": f"https://{source}.com/{repo}/releases/bundle.mpp",
                "created_at": timestamp,
            },
        )
        patch_path = self.patches_dir / f"{prefix}.json"
        save_json(
            patch_path,
            {"patches": patches if patches is not None else [self.app_patch()]},
        )
        return patch_path

    def app_patch(
        self, name: str = "Patch", package_name: str = "com.test.app"
    ) -> dict:
        return {
            "name": name,
            "compatiblePackages": [
                {"packageName": package_name, "targets": [{"version": "1.0"}]}
            ],
        }

    def run_update(self, mode: str = "default") -> dict:
        arguments = ["update.py"] + ([] if mode == "default" else [f"--{mode}"])
        with (
            patch.object(bundle_update.sys, "argv", arguments),
            patch("time.time", return_value=CURRENT_TIME_SECONDS),
        ):
            self.assertEqual(bundle_update.main(), 0)
        return load_json(self.public_path)

    def snapshot(self) -> dict[Path, bytes]:
        return {path: path.read_bytes() for path in self.state_paths}

    def test_invalid_current_patch_lists_are_excluded_without_old_patch_fallback(
        self,
    ) -> None:
        invalid_contents = [
            b"{broken",
            b"[]",
            b"{}",
            b'{"patches": []}',
            b"\xff",
            json.dumps(
                {"patches": [self.app_patch(package_name="com.example.app")]}
            ).encode(),
            b'{"patches": [{"name": ["Invalid name"]}]}',
            b'{"patches": [{"name": "Patch", "compatiblePackages": {"com.test.app": 5}}]}',
        ]
        for content in invalid_contents:
            with self.subTest(content=content):
                path = self.add_target()
                path.write_bytes(content)
                save_json(
                    self.public_path,
                    {
                        "bundles": [
                            {"repo": "owner/alpha", "patches": [{"name": "Old patch"}]}
                        ],
                        "store": {"com.old.app": {"name": "Old app"}},
                    },
                )
                catalog = self.run_update()
                self.assertEqual(catalog["bundles"], [])
                self.assertEqual(catalog["store"], {})
                self.assertEqual(catalog["compatibilities"], [])
                self.assertEqual(
                    load_json(self.repos_path)["owner/alpha"]["github"]["main"],
                    "downloaded-sha",
                )
                self.assertTrue(path.exists())
                summary = self.summary.call_args.args[0]
                self.assertIn("Invalid patch lists (1)", summary)
                self.assertIn("https://github.com/owner/alpha (main):", summary)
                self.assertNotIn("patches-bundle.json", summary)
                self.assertNotIn("invalid or excluded", summary)
        self.fetch_repo.assert_not_called()
        self.fetch_app.assert_not_called()

    def test_null_sha_prevents_reading_old_valid_patch_list(self) -> None:
        self.add_target(sha=None)
        self.assertEqual(self.run_update()["bundles"], [])
        self.fetch_repo.assert_not_called()
        self.summary.assert_not_called()

    def test_unusable_metadata_is_skipped_without_update_summary(self) -> None:
        for metadata in (
            None,
            [],
            {},
            {"download_url": "https://example.com/bundle.mpp"},
        ):
            with self.subTest(metadata=metadata):
                self.add_target()
                bundle_path = self.bundles_dir / "github~owner~alpha~main.json"
                if metadata is None:
                    bundle_path.unlink()
                else:
                    save_json(bundle_path, metadata)
                self.assertEqual(self.run_update()["bundles"], [])
                self.summary.assert_not_called()
        self.fetch_repo.assert_not_called()

    def test_missing_patch_list_has_branch_error_without_metadata_error(self) -> None:
        self.add_target().unlink()
        self.assertEqual(self.run_update()["bundles"], [])
        summary = self.summary.call_args.args[0]
        self.assertIn(
            "https://github.com/owner/alpha (main): Missing `patches-list.json`",
            summary,
        )
        self.assertNotIn("patches-bundle.json", summary)

    def test_patch_list_errors_are_attributed_to_their_source_and_branch(self) -> None:
        self.add_target(patches=[])
        self.add_target(source="gitlab", branch="dev").write_text(
            "{broken", encoding="utf-8"
        )
        self.assertEqual(self.run_update()["bundles"], [])
        summary = self.summary.call_args.args[0]
        self.assertIn("Invalid patch lists (2)", summary)
        self.assertIn(
            "https://github.com/owner/alpha (main): Empty `patches-list.json`", summary
        )
        self.assertIn(
            "https://gitlab.com/owner/alpha (dev): Invalid `patches-list.json`", summary
        )
        self.assertNotIn("https://github.com/owner/alpha (dev)", summary)
        self.assertNotIn("https://gitlab.com/owner/alpha (main)", summary)

    def test_invalid_patch_list_is_reported_when_other_source_is_valid(self) -> None:
        self.add_target(patches=[])
        self.add_target(source="gitlab", patches=[{"name": "Universal patch"}])
        self.assertEqual(self.run_update()["bundles"][0]["source"], "gitlab")
        summary = self.summary.call_args.args[0]
        self.assertIn("https://github.com/owner/alpha (main): Empty", summary)
        self.assertNotIn("https://gitlab.com/owner/alpha", summary)

    def test_newer_dev_is_selected_and_only_dev_patches_are_prerelease(self) -> None:
        self.add_target(patches=[self.app_patch("Stable patch")])
        self.add_target(
            branch="dev",
            timestamp=BUNDLE_TIME_MS + 1,
            patches=[self.app_patch("Stable patch"), self.app_patch("Dev patch")],
        )
        catalog = self.run_update()
        bundle = catalog["bundles"][0]
        self.assertNotIn("isPreRelease", bundle)
        patches = {patch["name"]: patch for patch in bundle["patches"]}
        self.assertNotIn("isPreRelease", patches["Stable patch"])
        self.assertTrue(patches["Dev patch"]["isPreRelease"])
        self.assertNotIn("isPreRelease", catalog["store"]["com.test.app"])

    def test_invalid_main_does_not_exclude_valid_dev(self) -> None:
        self.add_target().write_text("{broken", encoding="utf-8")
        self.add_target(branch="dev", patches=[self.app_patch("Dev patch")])
        catalog = self.run_update()
        self.assertTrue(catalog["bundles"][0]["isPreRelease"])
        self.assertTrue(catalog["store"]["com.test.app"]["isPreRelease"])
        summary = self.summary.call_args.args[0]
        self.assertIn("owner/alpha (main): Invalid `patches-list.json`", summary)
        self.assertNotIn("owner/alpha (dev)", summary)
        self.assertIn("Incomplete Apps", summary)

    def test_main_is_selected_when_newer_than_dev(self) -> None:
        self.add_target(
            timestamp=BUNDLE_TIME_MS + 1, patches=[self.app_patch("Main patch")]
        )
        self.add_target(branch="dev", patches=[self.app_patch("Dev patch")])
        self.assertEqual(
            self.run_update()["bundles"][0]["patches"][0]["name"], "Main patch"
        )

    def test_source_selection_keeps_timestamp_and_tie_rules(self) -> None:
        for github_time, gitlab_time, previous_source, expected in [
            (BUNDLE_TIME_MS, BUNDLE_TIME_MS + 1, None, "gitlab"),
            (BUNDLE_TIME_MS, BUNDLE_TIME_MS, "gitlab", "gitlab"),
            (BUNDLE_TIME_MS, BUNDLE_TIME_MS, None, "github"),
        ]:
            with self.subTest(expected=expected, previous=previous_source):
                self.add_target(timestamp=github_time)
                self.add_target(source="gitlab", timestamp=gitlab_time)
                save_json(
                    self.public_path,
                    {"bundles": [{"repo": "owner/alpha", "source": previous_source}]},
                )
                self.assertEqual(self.run_update()["bundles"][0]["source"], expected)

    def test_compatibility_is_deduplicated_once_without_changing_public_schema(
        self,
    ) -> None:
        self.add_target(
            patches=[self.app_patch("Alpha patch"), {"name": "Universal patch"}]
        )
        self.add_target(repo="owner/beta", patches=[self.app_patch("Beta patch")])
        catalog = self.run_update()
        self.assertEqual(
            catalog["compatibilities"],
            [[{"packageName": "com.test.app", "targets": [{"version": "1.0"}]}]],
        )
        for bundle in catalog["bundles"]:
            for patch_data in bundle["patches"]:
                self.assertNotIn("compatiblePackages", patch_data)
                if patch_data["name"] == "Universal patch":
                    self.assertNotIn("compatiblePackagesKey", patch_data)
                else:
                    self.assertEqual(patch_data["compatiblePackagesKey"], 0)
        self.assertIn(PACKAGE_UNIVERSAL, catalog["bundles"][0]["appFirstSeen"])

    def test_repository_metadata_failures_do_not_remove_valid_bundle(self) -> None:
        self.add_target()
        for details in (
            {"is_404": True, "error": "404 Not Found"},
            {"is_451": True, "error": "451 Unavailable"},
            {"error": "Request timed out"},
        ):
            with self.subTest(details=details):
                save_json(
                    self.public_path,
                    {
                        "bundles": [
                            {
                                "repo": "owner/alpha",
                                "stars": 17,
                                "avatarUrl": "https://example.com/cached.png",
                            }
                        ]
                    },
                )
                self.fetch_repo.return_value = details
                catalog = self.run_update(mode="daily")
                self.assertEqual(len(catalog["bundles"]), 1)
                self.assertEqual(catalog["bundles"][0]["stars"], 17)
                self.assertEqual(
                    catalog["bundles"][0]["avatarUrl"], "https://example.com/cached.png"
                )
                self.summary.assert_called()
                summary = self.summary.call_args.args[0]
                self.assertIn("Warnings (1)", summary)
                self.assertNotIn("Invalid patch lists", summary)

    def test_modes_keep_metadata_refresh_and_official_store_priority(self) -> None:
        self.add_target()
        existing_catalog = {
            "bundles": [{"repo": "owner/alpha", "firstSeen": FIRST_SEEN_MS}],
            "store": {
                "com.test.app": {
                    "name": "Cached app",
                    "iconUrl": "https://example.com/cached.png",
                    "description": "Cached description",
                    "minInstalls": 10,
                    "category": "Tools",
                    "firstSeen": FIRST_SEEN_MS,
                }
            },
        }
        save_json(
            self.official_path,
            {
                "bundles": [{"repo": "owner/alpha", "hotRank": 0}],
                "store": {"com.test.app": {"name": "Official app"}},
            },
        )
        for mode in ("default", "daily", "weekly"):
            with self.subTest(mode=mode):
                save_json(self.public_path, existing_catalog)
                self.fetch_repo.reset_mock()
                self.fetch_app.reset_mock()
                catalog = self.run_update(mode)
                self.assertEqual(
                    self.fetch_repo.call_count, 0 if mode == "default" else 1
                )
                self.assertEqual(
                    self.fetch_app.call_count, 1 if mode == "weekly" else 0
                )
                self.assertEqual(
                    catalog["store"]["com.test.app"]["name"], "Official app"
                )
                self.assertEqual(catalog["bundles"][0]["firstSeen"], FIRST_SEEN_MS)
                self.assertTrue(catalog["bundles"][0]["isOfficial"])

    def test_rename_preserves_history_hashes_and_first_seen(self) -> None:
        self.add_target()
        save_json(
            self.public_path,
            {"bundles": [{"repo": "owner/alpha", "firstSeen": FIRST_SEEN_MS}]},
        )
        old_history = {"patches": ["Patch"]}
        save_json(self.history_path, {"owner/alpha": old_history})
        self.fetch_repo.return_value = {"full_name": "owner/renamed", "stars": 7}
        catalog = self.run_update("daily")
        self.assertEqual(catalog["bundles"][0]["repo"], "owner/renamed")
        self.assertEqual(catalog["bundles"][0]["firstSeen"], FIRST_SEEN_MS)
        self.assertEqual(load_json(self.history_path), {"owner/renamed": old_history})
        self.assertEqual(set(load_json(self.hashes_path)), {"owner/renamed"})
        self.assertEqual(set(load_json(self.repos_path)), {"owner/renamed"})
        self.assertFalse(
            load_json(self.custom_path)["https://github.com/owner/alpha"]["enabled"]
        )

    def test_rename_collision_filters_apps_hashes_and_history_before_scraping(
        self,
    ) -> None:
        self.add_target(patches=[self.app_patch(package_name="com.alpha.app")])
        self.add_target(
            repo="owner/beta", patches=[self.app_patch(package_name="com.beta.app")]
        )
        save_json(
            self.history_path,
            {
                "owner/alpha": {"patches": ["Alpha"]},
                "owner/beta": {"patches": ["Beta"]},
            },
        )
        self.fetch_repo.return_value = {"full_name": "owner/beta", "stars": 7}
        catalog = self.run_update("daily")
        self.assertEqual(
            [bundle["repo"] for bundle in catalog["bundles"]], ["owner/beta"]
        )
        self.assertEqual(set(catalog["store"]), {"com.beta.app"})
        self.assertEqual(set(load_json(self.hashes_path)), {"owner/beta"})
        self.assertEqual(
            load_json(self.history_path), {"owner/beta": {"patches": ["Beta"]}}
        )
        self.assertEqual(
            [call.args[0] for call in self.fetch_app.call_args_list], ["com.beta.app"]
        )
        self.assertEqual(
            catalog["compatibilities"][0][0]["packageName"], "com.beta.app"
        )

    def test_failure_before_final_output_does_not_write_state_or_cleanup_files(
        self,
    ) -> None:
        self.add_target()
        save_json(self.history_path, {"owner/alpha": {"patches": ["Patch"]}})
        orphan_file = self.patches_dir / "orphan.json"
        save_json(orphan_file, {})
        snapshot = self.snapshot()
        self.fetch_repo.return_value = {"full_name": "owner/renamed", "stars": 7}
        with (
            patch.object(
                gplay_scrape,
                "process",
                side_effect=RuntimeError("Unexpected processing failure"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.run_update("daily")
        self.assertEqual(self.snapshot(), snapshot)
        self.assertTrue(orphan_file.exists())

    def test_successful_update_cleans_orphans_after_catalog_write(self) -> None:
        self.add_target()
        orphan_file = self.patches_dir / "orphan.json"
        save_json(orphan_file, {})

        def write_output(path: Path, data: dict) -> None:
            if path == self.public_path:
                self.assertTrue(orphan_file.exists())
            save_json(path, data)

        with patch.object(bundle_update, "save_json", side_effect=write_output):
            self.run_update()
        self.assertFalse(orphan_file.exists())

    def test_local_processing_keeps_state_and_orphans_until_final_update(self) -> None:
        self.add_target()
        orphan_file = self.patches_dir / "orphan.json"
        save_json(orphan_file, {})
        snapshot = self.snapshot()
        sources = {"owner/alpha": {"repo": "owner/alpha"}}
        local_hashes = local_parse.process(sources, {}, load_json(self.repos_path), {})
        self.assertEqual(set(local_hashes), {"owner/alpha"})
        self.assertIn("compatiblePackages", sources["owner/alpha"]["patches"][0])
        self.assertNotIn("compatiblePackagesKey", sources["owner/alpha"]["patches"][0])
        self.assertEqual(self.snapshot(), snapshot)
        self.assertTrue(orphan_file.exists())


if __name__ == "__main__":
    unittest.main()
