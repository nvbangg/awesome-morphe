import json
import tempfile
import unittest
import urllib.error
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import update as bundle_update
from common import repo_info
from common.utils import PACKAGE_UNIVERSAL, load_json, save_json
from discovery import audit_readme
from updater import gplay_scrape, local_parse, whats_new

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
        self.changelog_path = self.root / "whats-new.json"
        self.markdown_path = self.root / "whats-new.md"
        self.state_paths = [
            self.repos_path,
            self.public_path,
            self.hashes_path,
            self.history_path,
            self.custom_path,
        ]
        for path in [*self.state_paths, self.official_path]:
            save_json(path, {})
        save_json(self.changelog_path, [])
        changelog_patcher = patch.multiple(
            whats_new,
            WHATS_NEW_JSON_PATH=self.changelog_path,
            WHATS_NEW_PATH=self.markdown_path,
        )
        changelog_patcher.start()
        self.addCleanup(changelog_patcher.stop)
        clock_patcher = patch.object(whats_new, "datetime")
        self.clock = clock_patcher.start()
        self.clock.now.return_value = datetime.fromtimestamp(CURRENT_TIME_SECONDS, UTC)
        self.addCleanup(clock_patcher.stop)
        changelog_summary_patcher = patch.object(whats_new, "append_step_summary")
        changelog_summary_patcher.start()
        self.addCleanup(changelog_summary_patcher.stop)
        output_patcher = patch.object(bundle_update, "set_step_output")
        self.output = output_patcher.start()
        self.addCleanup(output_patcher.stop)
        path_patcher = patch.multiple(
            bundle_update,
            REPOS_JSON_PATH=self.repos_path,
            BUNDLES_JSON_PATH=self.public_path,
            HASHES_PATH=self.hashes_path,
            HISTORY_PATH=self.history_path,
            CUSTOM_JSON_PATH=self.custom_path,
            OFFICIAL_BUNDLES_PATH=self.official_path,
            BUNDLES_DIR=self.bundles_dir,
            PATCHES_DIR=self.patches_dir,
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
            side_effect=AssertionError("Update must not request repository metadata"),
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
        entry = repos.setdefault(f"https://{source}.com/{repo}", {})
        entry[branch] = sha
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
                            {
                                "source": "github",
                                "repo": "owner/alpha",
                                "patches": [{"name": "Old patch"}],
                            }
                        ],
                        "store": {"com.old.app": {"name": "Old app"}},
                    },
                )
                catalog = self.run_update()
                self.assertEqual(catalog["bundles"], [])
                self.assertEqual(catalog["store"], {})
                self.assertEqual(catalog["compatibilities"], [])
                self.assertEqual(
                    load_json(self.repos_path)["https://github.com/owner/alpha"][
                        "main"
                    ],
                    "downloaded-sha",
                )
                self.assertTrue(path.exists())
                summary = self.summary.call_args.args[0]
                self.assertIn("### Patch list (1)", summary)
                self.assertIn("https://github.com/owner/alpha: (main)", summary)
                self.assertNotIn("patches-bundle.json", summary)
                self.assertNotIn("invalid or excluded", summary)
        self.fetch_repo.assert_not_called()
        self.fetch_app.assert_not_called()

    def test_null_sha_prevents_reading_old_valid_patch_list(self) -> None:
        self.add_target(sha=None)
        self.add_target(branch="dev", sha=None)
        with patch.object(
            local_parse, "load_branch_data", wraps=local_parse.load_branch_data
        ) as load_branch:
            self.assertEqual(self.run_update()["bundles"], [])
        load_branch.assert_not_called()
        self.fetch_repo.assert_not_called()
        self.assertEqual(self.summary.call_args.args[0], "## 🔄 Update (0/0):")

    def test_unusable_metadata_does_not_repeat_fetch_errors(self) -> None:
        for metadata in (
            None,
            [],
            {},
            {"download_url": None},
        ):
            with self.subTest(metadata=metadata):
                self.add_target()
                bundle_path = self.bundles_dir / "github~owner~alpha~main.json"
                if metadata is None:
                    bundle_path.unlink()
                else:
                    save_json(bundle_path, metadata)
                self.assertEqual(self.run_update()["bundles"], [])
                self.assertEqual(self.summary.call_args.args[0], "## 🔄 Update (0/1):")
        self.fetch_repo.assert_not_called()

    def test_missing_patch_list_has_branch_error_without_metadata_error(self) -> None:
        self.add_target().unlink()
        self.assertEqual(self.run_update()["bundles"], [])
        summary = self.summary.call_args.args[0]
        self.assertIn(
            "https://github.com/owner/alpha: (main) Missing `patches-list.json`",
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
        self.assertIn("### Patch list (2)", summary)
        self.assertIn(
            "https://github.com/owner/alpha: (main) No patches found", summary
        )
        self.assertIn("https://gitlab.com/owner/alpha: (dev) Invalid data", summary)
        self.assertNotIn("https://github.com/owner/alpha: (dev)", summary)
        self.assertNotIn("https://gitlab.com/owner/alpha: (main)", summary)

    def test_invalid_patch_list_is_reported_when_other_source_is_valid(self) -> None:
        self.add_target(patches=[])
        self.add_target(source="gitlab", patches=[{"name": "Universal patch"}])
        self.assertEqual(self.run_update()["bundles"][0]["source"], "gitlab")
        summary = self.summary.call_args.args[0]
        self.assertIn(
            "https://github.com/owner/alpha: (main) No patches found", summary
        )
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
        with patch("builtins.print") as console:
            catalog = self.run_update()
        console.assert_any_call(
            "[-] https://github.com/owner/alpha (main): Invalid data"
        )
        self.assertTrue(catalog["bundles"][0]["isPreRelease"])
        self.assertTrue(catalog["store"]["com.test.app"]["isPreRelease"])
        summary = self.summary.call_args.args[0]
        self.assertNotIn("### Patch list", summary)
        self.assertIn("Incomplete Apps", summary)

    def test_invalid_dev_is_suppressed_when_main_is_valid(self) -> None:
        self.add_target(patches=[self.app_patch("Main patch")])
        self.add_target(branch="dev", patches=[])
        with patch("builtins.print") as console:
            catalog = self.run_update()
        console.assert_any_call(
            "[-] https://github.com/owner/alpha (dev): No patches found"
        )
        self.assertEqual(catalog["bundles"][0]["patches"][0]["name"], "Main patch")
        self.assertNotIn("isPreRelease", catalog["bundles"][0])
        self.assertNotIn("### Patch list", self.summary.call_args.args[0])

    def test_identical_invalid_branches_have_one_summary_entry(self) -> None:
        self.add_target().write_text("{broken", encoding="utf-8")
        self.add_target(branch="dev").write_text("[]", encoding="utf-8")
        repos_snapshot = self.repos_path.read_bytes()
        self.assertEqual(self.run_update()["bundles"], [])
        summary = self.summary.call_args.args[0]
        self.assertIn("### Patch list (1)", summary)
        self.assertIn("https://github.com/owner/alpha: Invalid data", summary)
        self.assertNotIn("(main)", summary)
        self.assertNotIn("(dev)", summary)
        self.assertEqual(summary.count("- https://"), 1)
        self.assertEqual(self.repos_path.read_bytes(), repos_snapshot)

    def test_different_invalid_branches_share_one_repository_entry(self) -> None:
        self.add_target(patches=[])
        self.add_target(branch="dev").write_text("{broken", encoding="utf-8")
        self.assertEqual(self.run_update()["bundles"], [])
        summary = self.summary.call_args.args[0]
        self.assertIn("### Patch list (1)", summary)
        self.assertIn(
            "https://github.com/owner/alpha: (main) No patches found; "
            "(dev) Invalid data",
            summary,
        )
        self.assertEqual(summary.count("- https://"), 1)

    def test_null_sha_does_not_hide_other_branch_errors_or_use_stale_files(
        self,
    ) -> None:
        for invalid_branch, skipped_branch in (("main", "dev"), ("dev", "main")):
            with self.subTest(invalid_branch=invalid_branch):
                self.add_target(branch=invalid_branch, patches=[])
                skipped_patch_path = self.add_target(branch=skipped_branch, sha=None)
                skipped_bundle_path = (
                    self.bundles_dir / f"github~owner~alpha~{skipped_branch}.json"
                )
                with patch.object(
                    local_parse, "load_json", wraps=load_json
                ) as read_local:
                    self.assertEqual(self.run_update()["bundles"], [])
                read_paths = [call.args[0] for call in read_local.call_args_list]
                self.assertNotIn(skipped_patch_path, read_paths)
                self.assertNotIn(skipped_bundle_path, read_paths)
                summary = self.summary.call_args.args[0]
                self.assertIn("### Patch list (1)", summary)
                self.assertIn(
                    f"https://github.com/owner/alpha: ({invalid_branch}) No patches found",
                    summary,
                )
                self.assertNotIn(f"({skipped_branch})", summary)

    def test_main_is_selected_when_newer_than_dev(self) -> None:
        self.add_target(
            timestamp=BUNDLE_TIME_MS + 1, patches=[self.app_patch("Main patch")]
        )
        self.add_target(branch="dev", patches=[self.app_patch("Dev patch")])
        self.assertEqual(
            self.run_update()["bundles"][0]["patches"][0]["name"], "Main patch"
        )

    def test_sources_remain_independent_even_with_the_same_repository_path(
        self,
    ) -> None:
        self.add_target(patches=[self.app_patch("GitHub patch")])
        self.add_target(
            source="gitlab",
            timestamp=BUNDLE_TIME_MS + 1,
            patches=[self.app_patch("GitLab patch")],
        )
        catalog = self.run_update()
        self.assertEqual(
            {bundle["source"] for bundle in catalog["bundles"]}, {"github", "gitlab"}
        )
        self.assertEqual(len(catalog["bundles"]), 2)
        self.assertTrue(
            self.summary.call_args.args[0].startswith("## 🔄 Update (2/2):")
        )

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

    def test_repository_metadata_is_read_locally_without_network(self) -> None:
        self.add_target()
        repos = load_json(self.repos_path)
        repos["https://github.com/owner/alpha"].update(
            {
                "stars": 17,
                "description": "Cached repo",
                "avatarUrl": "https://example.com/cached.png",
            }
        )
        save_json(self.repos_path, repos)
        catalog = self.run_update("daily")
        self.assertEqual(catalog["bundles"][0]["stars"], 17)
        self.assertEqual(
            catalog["bundles"][0]["avatarUrl"], "https://example.com/cached.png"
        )
        self.assertEqual(catalog["bundles"][0]["repoDescription"], "Cached repo")
        self.fetch_repo.assert_not_called()
        self.assertNotIn("Repository metadata", self.summary.call_args.args[0])

    def test_incomplete_apps_alone_are_grouped_under_update(self) -> None:
        self.add_target()
        self.run_update()
        self.summary.assert_called_once()
        summary = self.summary.call_args.args[0]
        self.assertTrue(summary.startswith("## 🔄 Update (1/1):\n\n"))
        self.assertIn("### Incomplete Apps (1)\n\n", summary)
        self.assertNotIn("### Patch list", summary)
        self.assertNotIn("### Repository metadata", summary)

    def test_archived_repository_keeps_catalog_flag_without_duplicate_warning(
        self,
    ) -> None:
        self.add_target()
        repos = load_json(self.repos_path)
        repos["https://github.com/owner/alpha"]["isArchived"] = True
        save_json(self.repos_path, repos)
        catalog = self.run_update()
        self.assertTrue(catalog["bundles"][0]["isArchived"])
        self.assertNotIn("Repository metadata", self.summary.call_args.args[0])

    def test_modes_keep_metadata_refresh_and_official_store_priority(self) -> None:
        self.add_target()
        existing_catalog = {
            "bundles": [
                {"source": "github", "repo": "owner/alpha", "firstSeen": FIRST_SEEN_MS}
            ],
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
                "bundles": [{"source": "github", "repo": "owner/alpha", "hotRank": 0}],
                "store": {"com.test.app": {"name": "Official app"}},
            },
        )
        for mode in ("default", "daily", "weekly"):
            with self.subTest(mode=mode):
                save_json(self.public_path, existing_catalog)
                self.fetch_repo.reset_mock()
                self.fetch_app.reset_mock()
                catalog = self.run_update(mode)
                self.assertEqual(self.fetch_repo.call_count, 0)
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
            {
                "bundles": [
                    {
                        "source": "github",
                        "repo": "owner/alpha",
                        "firstSeen": FIRST_SEEN_MS,
                    }
                ]
            },
        )
        old_history = {"com.test.app": ["Patch"]}
        save_json(self.history_path, {"https://github.com/owner/alpha": old_history})
        repos = load_json(self.repos_path)
        repos["https://github.com/owner/alpha"]["renamedTo"] = (
            "https://github.com/owner/renamed"
        )
        save_json(self.repos_path, repos)
        catalog = self.run_update("daily")
        self.assertEqual(catalog["bundles"][0]["repo"], "owner/renamed")
        self.assertEqual(catalog["bundles"][0]["firstSeen"], FIRST_SEEN_MS)
        self.assertEqual(
            load_json(self.history_path),
            {"https://github.com/owner/renamed": old_history},
        )
        self.assertEqual(
            set(load_json(self.hashes_path)), {"https://github.com/owner/renamed"}
        )
        self.assertEqual(
            set(load_json(self.repos_path)), {"https://github.com/owner/renamed"}
        )
        self.assertFalse(
            load_json(self.custom_path)["https://github.com/owner/alpha"]["enabled"]
        )
        self.assertNotIn(
            "renamedTo", load_json(self.repos_path)["https://github.com/owner/renamed"]
        )
        self.assertTrue((self.bundles_dir / "github~owner~renamed~main.json").is_file())
        self.assertTrue((self.patches_dir / "github~owner~renamed~main.json").is_file())

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
                "https://github.com/owner/alpha": {"com.alpha.app": ["Patch"]},
                "https://github.com/owner/beta": {"com.beta.app": ["Patch"]},
            },
        )
        repos = load_json(self.repos_path)
        repos["https://github.com/owner/alpha"]["renamedTo"] = (
            "https://github.com/owner/beta"
        )
        save_json(self.repos_path, repos)
        catalog = self.run_update("daily")
        self.assertEqual(
            [bundle["repo"] for bundle in catalog["bundles"]], ["owner/beta"]
        )
        self.assertEqual(set(catalog["store"]), {"com.beta.app"})
        self.assertEqual(
            set(load_json(self.hashes_path)), {"https://github.com/owner/beta"}
        )
        self.assertEqual(
            load_json(self.history_path),
            {"https://github.com/owner/beta": {"com.beta.app": ["Patch"]}},
        )
        self.assertEqual(
            [call.args[0] for call in self.fetch_app.call_args_list], ["com.beta.app"]
        )
        self.assertEqual(
            catalog["compatibilities"][0][0]["packageName"], "com.beta.app"
        )
        self.assertTrue(
            self.summary.call_args.args[0].startswith("## 🔄 Update (2/2):")
        )

    def test_counts_only_repositories_with_hashes_and_deduplicates_sources(
        self,
    ) -> None:
        self.add_target()
        self.add_target(source="gitlab", branch="dev")
        self.add_target(repo="owner/invalid", patches=[])
        self.add_target(repo="owner/skipped", sha=None)
        catalog = self.run_update()
        self.assertEqual(len(catalog["bundles"]), 2)
        self.assertTrue(
            self.summary.call_args.args[0].startswith("## 🔄 Update (2/3):")
        )

    def test_empty_repository_list_still_reports_zero_counts(self) -> None:
        self.assertEqual(self.run_update()["bundles"], [])
        self.assertEqual(self.summary.call_args.args[0], "## 🔄 Update (0/0):")
        self.fetch_repo.assert_not_called()
        self.fetch_app.assert_not_called()

    def test_default_update_does_not_advance_history_before_daily(self) -> None:
        self.add_target()
        self.run_update()
        self.assertEqual(load_json(self.history_path), {})
        self.assertEqual(load_json(self.changelog_path), [])
        self.output.assert_not_called()
        with patch.object(
            whats_new,
            "load_json",
            side_effect=lambda path, default: (
                load_json(path, default)
                if path == self.changelog_path
                else self.fail("What's New must not reload the catalog or history")
            ),
        ):
            self.run_update("daily")
        repo_url = "https://github.com/owner/alpha"
        self.assertEqual(
            load_json(self.history_path), {repo_url: {"com.test.app": ["Patch"]}}
        )
        self.assertTrue(load_json(self.changelog_path)[0]["bundles"][repo_url]["isNew"])
        self.assertTrue(self.markdown_path.is_file())
        self.output.assert_called_once_with("success", "true")

    def test_unavailable_and_invalid_bundles_keep_history_without_being_published(
        self,
    ) -> None:
        unavailable_url = "https://github.com/owner/unavailable"
        invalid_url = "https://github.com/owner/invalid"
        removed_url = "https://github.com/owner/removed"
        saved_history = {
            unavailable_url: {"com.old.app": ["Old patch"]},
            invalid_url: {"com.invalid.app": ["Old patch"]},
            removed_url: {"com.removed.app": ["Old patch"]},
        }
        save_json(self.history_path, saved_history)
        self.add_target(repo="owner/unavailable", sha=None)
        self.add_target(repo="owner/invalid", patches=[])
        self.add_target(
            repo="owner/template",
            patches=[self.app_patch(package_name="com.example.app")],
        )
        for mode in ("default", "daily", "weekly"):
            with self.subTest(mode=mode):
                catalog = self.run_update(mode)
                self.assertEqual(catalog["bundles"], [])
                self.assertNotIn("com.old.app", catalog["store"])
                self.assertEqual(load_json(self.history_path), saved_history)
                self.assertEqual(load_json(self.changelog_path), [])

    def test_returning_bundle_only_announces_added_patches(self) -> None:
        repo_url = "https://github.com/owner/alpha"
        save_json(self.history_path, {repo_url: {"com.test.app": ["Patch"]}})
        self.add_target(sha=None)
        self.run_update("daily")
        self.add_target()
        self.run_update("daily")
        self.assertEqual(load_json(self.changelog_path), [])
        self.add_target(patches=[self.app_patch(), self.app_patch(name="Added patch")])
        self.run_update("daily")
        changes = load_json(self.changelog_path)[0]["bundles"][repo_url]
        self.assertNotIn("isNew", changes)
        self.assertEqual(
            changes["apps"], {"com.test.app": {"patches": ["Added patch"]}}
        )

    def test_known_app_in_new_bundle_is_not_a_new_app_in_telegram(self) -> None:
        old_url = "https://github.com/owner/unavailable"
        save_json(self.history_path, {old_url: {"com.test.app": ["Patch"]}})
        self.add_target()
        self.run_update("daily")
        self.assertIn(old_url, load_json(self.history_path))
        markdown = self.markdown_path.read_text(encoding="utf-8")
        self.assertIn("📦 (✨New)", markdown)
        self.assertNotIn("📱 (✨New)", markdown)

    def test_known_app_added_to_existing_bundle_is_only_a_bundle_addition(self) -> None:
        repo_url = "https://github.com/owner/alpha"
        save_json(
            self.history_path,
            {
                "https://github.com/owner/unavailable": {"com.test.app": ["Patch"]},
                repo_url: {"com.other.app": ["Other patch"]},
            },
        )
        self.add_target(
            patches=[
                self.app_patch(),
                self.app_patch(name="Other patch", package_name="com.other.app"),
            ]
        )
        self.run_update("weekly")
        changes = load_json(self.changelog_path)[0]["bundles"][repo_url]
        self.assertNotIn("isNew", changes)
        self.assertEqual(
            changes["apps"],
            {"com.test.app": {"patches": ["Patch"], "isNew": True}},
        )
        markdown = self.markdown_path.read_text(encoding="utf-8")
        self.assertNotIn("📱 (✨New)", markdown)
        self.assertNotIn("📦 (✨New)", markdown)
        self.assertIn("com.test.app", markdown)

    def test_unchanged_daily_removes_the_previous_notification(self) -> None:
        self.add_target()
        self.run_update("daily")
        history = self.history_path.read_bytes()
        changelog = self.changelog_path.read_bytes()
        self.assertTrue(self.markdown_path.exists())
        self.run_update("daily")
        self.assertFalse(self.markdown_path.exists())
        self.assertEqual(self.history_path.read_bytes(), history)
        self.assertEqual(self.changelog_path.read_bytes(), changelog)

    def test_same_day_skip_preserves_baseline_and_removes_stale_notification(
        self,
    ) -> None:
        self.add_target()
        self.run_update("daily")
        history = self.history_path.read_bytes()
        changelog = self.changelog_path.read_bytes()
        self.assertTrue(self.markdown_path.exists())
        self.add_target(patches=[self.app_patch(name="Next patch")])
        self.run_update("daily")
        self.assertEqual(self.history_path.read_bytes(), history)
        self.assertEqual(self.changelog_path.read_bytes(), changelog)
        self.assertFalse(self.markdown_path.exists())
        self.clock.now.return_value += timedelta(days=1)
        self.run_update("daily")
        changes = load_json(self.changelog_path)[0]["bundles"]
        self.assertEqual(
            changes["https://github.com/owner/alpha"]["apps"],
            {"com.test.app": {"patches": ["Next patch"]}},
        )

    def test_changelog_failure_does_not_mark_update_successful_or_advance_history(
        self,
    ) -> None:
        self.add_target()
        with (
            patch.object(
                whats_new, "generate", side_effect=OSError("Cannot write changelog")
            ),
            self.assertRaises(OSError),
        ):
            self.run_update("daily")
        self.output.assert_not_called()
        self.assertEqual(load_json(self.history_path), {})

    def test_failure_before_final_output_does_not_write_state_or_cleanup_files(
        self,
    ) -> None:
        self.add_target()
        save_json(
            self.history_path,
            {"https://github.com/owner/alpha": {"patches": ["Patch"]}},
        )
        orphan_file = self.patches_dir / "orphan.json"
        save_json(orphan_file, {})
        repos = load_json(self.repos_path)
        repos["https://github.com/owner/alpha"]["renamedTo"] = (
            "https://github.com/owner/renamed"
        )
        save_json(self.repos_path, repos)
        snapshot = self.snapshot()
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
        sources = {"https://github.com/owner/alpha": {"repo": "owner/alpha"}}
        local_hashes = local_parse.process(sources, {}, load_json(self.repos_path), {})
        self.assertEqual(set(local_hashes), {"https://github.com/owner/alpha"})
        self.assertIn(
            "compatiblePackages",
            sources["https://github.com/owner/alpha"]["patches"][0],
        )
        self.assertNotIn(
            "compatiblePackagesKey",
            sources["https://github.com/owner/alpha"]["patches"][0],
        )
        self.assertEqual(self.snapshot(), snapshot)
        self.assertTrue(orphan_file.exists())

    def test_app_name_comes_from_selected_branch(self) -> None:
        main = self.app_patch()
        main["compatiblePackages"][0]["name"] = "Stable app"
        dev = self.app_patch()
        dev["compatiblePackages"][0]["name"] = "Dev app"
        self.add_target(timestamp=BUNDLE_TIME_MS + 1, patches=[main])
        self.add_target(branch="dev", patches=[dev])
        self.assertEqual(
            self.run_update()["store"]["com.test.app"]["name"], "Stable app"
        )

    def test_official_status_and_metadata_do_not_leak_across_hosts(self) -> None:
        self.add_target()
        self.add_target(source="gitlab")
        repos = load_json(self.repos_path)
        repos["https://github.com/owner/alpha"].update(
            {"stars": 100, "description": "GitHub"}
        )
        repos["https://gitlab.com/owner/alpha"].update(
            {"stars": 5, "description": "GitLab"}
        )
        save_json(self.repos_path, repos)
        save_json(
            self.official_path,
            {"bundles": [{"source": "github", "repo": "owner/alpha", "hotRank": 0}]},
        )
        bundles = {bundle["source"]: bundle for bundle in self.run_update()["bundles"]}
        self.assertTrue(bundles["github"]["isOfficial"])
        self.assertNotIn("isOfficial", bundles["gitlab"])
        self.assertEqual(bundles["github"]["stars"], 100)
        self.assertEqual(bundles["gitlab"]["stars"], 5)

    def test_rename_preserves_other_host_and_keeps_new_files_readable(self) -> None:
        self.add_target()
        self.add_target(source="gitlab")
        repos = load_json(self.repos_path)
        repos["https://github.com/owner/alpha"]["renamedTo"] = (
            "https://github.com/owner/new"
        )
        save_json(self.repos_path, repos)
        catalog = self.run_update()
        self.assertEqual(
            {(bundle["source"], bundle["repo"]) for bundle in catalog["bundles"]},
            {("github", "owner/new"), ("gitlab", "owner/alpha")},
        )
        self.assertIn("https://gitlab.com/owner/alpha", load_json(self.repos_path))
        self.assertEqual(self.run_update(), catalog)


class RepositoryMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        sleep_patcher = patch.object(repo_info.time, "sleep")
        sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)
        network_patcher = patch(
            "urllib.request.urlopen",
            side_effect=AssertionError("Unexpected network access"),
        )
        self.open_url = network_patcher.start()
        self.addCleanup(network_patcher.stop)

    def http_error(self, code: int) -> urllib.error.HTTPError:
        error = urllib.error.HTTPError(
            "https://example.com", code, "Failed", None, None
        )
        self.addCleanup(error.close)
        return error

    def test_github_http_errors_keep_actual_status_and_audit_flags(self) -> None:
        for code in (404, 451, 403, 503):
            with (
                self.subTest(code=code),
                patch.object(repo_info, "fetch", side_effect=self.http_error(code)),
            ):
                details = repo_info.fetch_repo_details("https://github.com/owner/alpha")
                expected = {"error": f"Request failed (HTTP {code})"}
                if code in repo_info.UNAVAILABLE_HTTP_CODES:
                    expected[f"is_{code}"] = True
                self.assertEqual(details, expected)

    def test_connection_error_reports_reason_without_fabricating_http_status(
        self,
    ) -> None:
        with patch.object(
            repo_info, "fetch", side_effect=urllib.error.URLError("DNS lookup failed")
        ):
            details = repo_info.fetch_repo_details("https://github.com/owner/alpha")
        self.assertEqual(details, {"error": "Request failed: DNS lookup failed"})

    def test_gitlab_request_errors_report_actual_status_or_exception_reason(
        self,
    ) -> None:
        for error, expected in (
            (self.http_error(503), "Request failed (HTTP 503)"),
            (urllib.error.URLError("timed out"), "Request failed: timed out"),
        ):
            with self.subTest(error=error):
                self.open_url.side_effect = error
                self.assertEqual(
                    repo_info.fetch_gitlab_repo_details("owner/alpha"),
                    {"error": expected},
                )

    def test_missing_gitlab_project_does_not_claim_an_http_error(self) -> None:
        self.open_url.side_effect = None
        self.open_url.return_value.__enter__.return_value.read.return_value = (
            b'{"data": {"project": null}}'
        )
        self.assertEqual(
            repo_info.fetch_gitlab_repo_details("owner/alpha"),
            {"is_404": True, "error": "Repository not found or inaccessible"},
        )

    def test_audit_still_classifies_unavailable_repositories(self) -> None:
        repo_url = "https://github.com/owner/alpha"
        for code in repo_info.UNAVAILABLE_HTTP_CODES:
            with (
                self.subTest(code=code),
                patch.object(repo_info, "fetch", side_effect=self.http_error(code)),
                patch.object(audit_readme, "load_lines", side_effect=[[repo_url], []]),
            ):
                summary = audit_readme.audit_repos_and_links()
                self.assertIn(f"{repo_url}: {code}", summary)
                self.assertNotIn("Other Errors", summary)
                self.assertIn("#### Unavailable (1)", summary)


class WhatsNewIdentityTests(unittest.TestCase):
    def history(self, catalog: dict) -> dict:
        history = {}
        for bundle in catalog["bundles"]:
            bundle_apps = {}
            for patch_data in bundle["patches"]:
                whats_new.collect_patch_history(
                    bundle_apps,
                    patch_data["name"],
                    patch_data.get("compatiblePackages"),
                )
            history[f"https://{bundle['source']}.com/{bundle['repo']}"] = {
                package_name: sorted(patches)
                for package_name, patches in bundle_apps.items()
            }
        return history

    def catalog(self) -> dict:
        return {
            "bundles": [
                {
                    "source": source,
                    "repo": "owner/alpha",
                    "name": source.title(),
                    "hotRank": index,
                    "patches": [{"name": source + " patch"}],
                }
                for index, source in enumerate(("github", "gitlab"))
            ],
            "store": {},
        }

    def test_baseline_and_diff_preserve_both_hosts(self) -> None:
        catalog = self.catalog()
        baseline = self.history(catalog)
        self.assertEqual(
            set(baseline),
            {"https://github.com/owner/alpha", "https://gitlab.com/owner/alpha"},
        )
        names, order = whats_new.extract_bundle_metadata(catalog["bundles"])
        self.assertEqual(len(names), 2)
        changes = whats_new.build_json_diff({}, baseline, {}, order)
        markdown = whats_new.generate_markdown(changes, {}, {}, names, order)
        self.assertIn("github=owner/alpha", markdown)
        self.assertIn("gitlab=owner/alpha", markdown)
        self.assertNotIn("github=https", markdown)
        self.assertEqual(whats_new.build_json_diff(baseline, baseline, {}, order), {})

    def test_missing_bundle_name_uses_the_repository_name(self) -> None:
        catalog = self.catalog()
        for bundle in catalog["bundles"]:
            bundle.pop("name")
        names, order = whats_new.extract_bundle_metadata(catalog["bundles"])
        self.assertEqual(set(names.values()), {"alpha"})
        changes = whats_new.build_json_diff({}, self.history(catalog), {}, order)
        markdown = whats_new.generate_markdown(changes, {}, {}, {}, order)
        self.assertIn("github=owner/alpha", markdown)
        self.assertIn("gitlab=owner/alpha", markdown)

    def test_missing_install_count_does_not_break_changelog_sorting(self) -> None:
        key = whats_new.get_app_sort_key(
            "com.test.app", {"com.test.app": {"name": "Test", "minInstalls": None}}
        )
        self.assertEqual(key[1], 0)

    def test_patch_history_filters_packages_deduplicates_and_keeps_universal(
        self,
    ) -> None:
        bundle_apps = {}
        compatibility = [
            {"packageName": "com.test.app"},
            {"packageName": "com.test.app"},
            {"packageName": "com.example.app"},
            {"packageName": "invalid"},
        ]
        whats_new.collect_patch_history(bundle_apps, "Patch", compatibility)
        whats_new.collect_patch_history(bundle_apps, "Patch", compatibility)
        whats_new.collect_patch_history(bundle_apps, "Universal patch", None)
        whats_new.collect_patch_history(
            bundle_apps, "Template patch", [{"packageName": "com.example.app"}]
        )
        self.assertEqual(
            bundle_apps,
            {
                "com.test.app": {"Patch"},
                PACKAGE_UNIVERSAL: {"Universal patch", "Template patch"},
            },
        )


if __name__ == "__main__":
    unittest.main()
