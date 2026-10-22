import json
from datetime import UTC, datetime, timedelta
from http.client import HTTPException
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

import pytest
from google_play_scraper.exceptions import ExtraHTTPError

import update as bundle_update
from common import repo_info
from common.utils import PACKAGE_UNIVERSAL, load_json, save_json
from updater import gplay_scrape, local_data, whats_new

CURRENT_TIME_SECONDS = 1_800_000_000
BUNDLE_TIME_MS = 1_700_000_000_000
FIRST_SEEN_MS = 1_600_000_000_000


class TestBundleUpdate:
    @pytest.fixture(autouse=True)
    def prepare(self, tmp_path: Path, patch_context) -> None:
        self.patch_context = patch_context
        self.root = tmp_path
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
        self.patch_context.enter_context(
            patch.multiple(
                whats_new,
                WHATS_NEW_JSON_PATH=self.changelog_path,
                WHATS_NEW_PATH=self.markdown_path,
            )
        )
        self.clock = self.patch_context.enter_context(
            patch.object(whats_new, "datetime")
        )
        self.clock.now.return_value = datetime.fromtimestamp(CURRENT_TIME_SECONDS, UTC)
        self.patch_context.enter_context(patch.object(whats_new, "append_step_summary"))
        self.output = self.patch_context.enter_context(
            patch.object(bundle_update, "set_step_output")
        )
        self.patch_context.enter_context(
            patch.multiple(
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
        )
        self.patch_context.enter_context(
            patch.multiple(
                local_data, BUNDLES_DIR=self.bundles_dir, PATCHES_DIR=self.patches_dir
            )
        )
        self.patch_context.enter_context(
            patch.object(gplay_scrape, "OFFICIAL_BUNDLES_PATH", self.official_path)
        )
        self.fetch_repo = self.patch_context.enter_context(
            patch.object(
                repo_info,
                "fetch_repo_details",
                side_effect=AssertionError(
                    "Update must not request repository metadata"
                ),
            )
        )
        self.fetch_app = self.patch_context.enter_context(
            patch.object(gplay_scrape, "fetch_app_details", return_value=(None, False))
        )
        self.summary = self.patch_context.enter_context(
            patch.object(bundle_update, "append_step_summary")
        )

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
            assert bundle_update.main() == 0
        return load_json(self.public_path)

    @pytest.mark.parametrize("result_count", (9, 10))
    def test_patch_list_summary_collapses_at_ten_repositories(
        self, result_count, capsys
    ) -> None:
        save_json(self.repos_path, {})
        for index in range(result_count):
            self.add_target(repo=f"owner/repo-{index}", patches=[])
        self.run_update()
        summary = self.summary.call_args.args[0]
        assert f"### Patch list ({result_count})" in summary
        assert ("<details>" in summary) == (result_count >= 10)
        assert summary.count("- https://") == result_count
        console = capsys.readouterr().out
        assert f"Patch list: {result_count} repositories" in console
        assert "https://github.com/owner/repo-" not in console
        assert "Excluding" not in console

    def snapshot(self) -> dict[Path, bytes]:
        return {path: path.read_bytes() for path in self.state_paths}

    @pytest.mark.parametrize(
        "rejected",
        (
            None,
            7,
            {},
            {"name": None},
            {"name": 7},
            {"name": []},
            {"name": ""},
            {"name": " "},
        ),
    )
    def test_rejected_patch_does_not_change_app_hash_or_updates(self, rejected) -> None:
        valid_patch = self.app_patch()
        self.add_target(patches=[valid_patch])
        baseline = self.run_update()
        baseline_hashes = load_json(self.hashes_path)
        if isinstance(rejected, dict):
            rejected = {
                **rejected,
                "compatiblePackages": valid_patch["compatiblePackages"],
            }
        self.add_target(patches=[valid_patch, rejected])
        catalog = self.run_update()
        assert catalog == baseline
        assert load_json(self.hashes_path) == baseline_hashes

    @pytest.mark.parametrize(
        "field,value",
        (
            ("description", "Changed description"),
            ("options", [{"key": "setting", "title": "Changed option"}]),
            (
                "compatiblePackages",
                [{"packageName": "com.test.app", "targets": [{"version": "2.0"}]}],
            ),
        ),
    )
    def test_accepted_patch_content_still_changes_app_hash(self, field, value) -> None:
        valid_patch = self.app_patch()
        self.add_target(patches=[valid_patch])
        self.run_update()
        previous_hashes = load_json(self.hashes_path)
        self.add_target(
            patches=[{**valid_patch, field: value}], timestamp=BUNDLE_TIME_MS + 1
        )
        catalog = self.run_update()
        assert load_json(self.hashes_path) != previous_hashes
        assert catalog["bundles"][0]["appUpdates"]["com.test.app"] == BUNDLE_TIME_MS + 1

    @pytest.mark.parametrize(
        "invalid_kind",
        (
            "invalid-json",
            "wrong-root",
            "missing-patches",
            "empty-patches",
            "invalid-utf8",
            "template-only",
            "invalid-name",
            "invalid-compatibility",
        ),
    )
    def test_invalid_current_patch_lists_are_excluded_without_old_patch_fallback(
        self, invalid_kind
    ) -> None:
        content = {
            "invalid-json": b"{broken",
            "wrong-root": b"[]",
            "missing-patches": b"{}",
            "empty-patches": b'{"patches": []}',
            "invalid-utf8": b"\xff",
            "template-only": json.dumps(
                {"patches": [self.app_patch(package_name="com.example.app")]}
            ).encode(),
            "invalid-name": b'{"patches": [{"name": ["Invalid name"]}]}',
            "invalid-compatibility": b'{"patches": [{"name": "Patch", "compatiblePackages": {"com.test.app": 5}}]}',
        }[invalid_kind]
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
        assert catalog["bundles"] == []
        assert catalog["store"] == {}
        assert catalog["compatibilities"] == []
        assert (
            load_json(self.repos_path)["https://github.com/owner/alpha"]["main"]
            == "downloaded-sha"
        )
        assert path.exists()
        summary = self.summary.call_args.args[0]
        assert "### Patch list (1)" in summary
        assert "https://github.com/owner/alpha: (main)" in summary
        assert "patches-bundle.json" not in summary
        assert "invalid or excluded" not in summary

    def test_null_sha_prevents_reading_old_valid_patch_list(self) -> None:
        self.add_target(sha=None)
        self.add_target(branch="dev", sha=None)
        with patch.object(
            local_data, "load_branch_data", wraps=local_data.load_branch_data
        ) as load_branch:
            assert self.run_update()["bundles"] == []
        load_branch.assert_not_called()
        self.fetch_repo.assert_not_called()
        assert self.summary.call_args.args[0] == "## 🔄 Update (0/0):"

    @pytest.mark.parametrize("metadata", (None, [], {}, {"download_url": None}))
    def test_unusable_metadata_does_not_repeat_fetch_errors(self, metadata) -> None:
        self.add_target()
        bundle_path = self.bundles_dir / "github~owner~alpha~main.json"
        if metadata is None:
            bundle_path.unlink()
        else:
            save_json(bundle_path, metadata)
        assert self.run_update()["bundles"] == []
        assert self.summary.call_args.args[0] == "## 🔄 Update (0/1):"
        self.fetch_repo.assert_not_called()

    def test_missing_patch_list_has_branch_error_without_metadata_error(self) -> None:
        self.add_target().unlink()
        assert self.run_update()["bundles"] == []
        summary = self.summary.call_args.args[0]
        assert (
            "https://github.com/owner/alpha: (main) Missing `patches-list.json`"
            in summary
        )
        assert "patches-bundle.json" not in summary

    def test_patch_list_errors_are_attributed_to_their_source_and_branch(self) -> None:
        self.add_target(patches=[])
        self.add_target(source="gitlab", branch="dev").write_text(
            "{broken", encoding="utf-8"
        )
        assert self.run_update()["bundles"] == []
        summary = self.summary.call_args.args[0]
        assert "### Patch list (2)" in summary
        assert "https://github.com/owner/alpha: (main) No patches found" in summary
        assert "https://gitlab.com/owner/alpha: (dev) Invalid data" in summary
        assert "https://github.com/owner/alpha: (dev)" not in summary
        assert "https://gitlab.com/owner/alpha: (main)" not in summary

    def test_invalid_patch_list_is_reported_when_other_source_is_valid(self) -> None:
        self.add_target(patches=[])
        self.add_target(source="gitlab", patches=[{"name": "Universal patch"}])
        assert self.run_update()["bundles"][0]["source"] == "gitlab"
        summary = self.summary.call_args.args[0]
        assert "https://github.com/owner/alpha: (main) No patches found" in summary
        assert "https://gitlab.com/owner/alpha" not in summary

    def test_newer_dev_is_selected_and_only_dev_patches_are_prerelease(self) -> None:
        self.add_target(patches=[self.app_patch("Stable patch")])
        self.add_target(
            branch="dev",
            timestamp=BUNDLE_TIME_MS + 1,
            patches=[self.app_patch("Stable patch"), self.app_patch("Dev patch")],
        )
        catalog = self.run_update()
        bundle = catalog["bundles"][0]
        assert "isPreRelease" not in bundle
        patches = {patch["name"]: patch for patch in bundle["patches"]}
        assert "isPreRelease" not in patches["Stable patch"]
        assert patches["Dev patch"]["isPreRelease"]
        assert "isPreRelease" not in catalog["store"]["com.test.app"]

    def test_invalid_main_does_not_exclude_valid_dev(self, capsys) -> None:
        self.add_target().write_text("{broken", encoding="utf-8")
        self.add_target(branch="dev", patches=[self.app_patch("Dev patch")])
        catalog = self.run_update()
        assert "https://github.com/owner/alpha" not in capsys.readouterr().out
        assert catalog["bundles"][0]["isPreRelease"]
        assert catalog["store"]["com.test.app"]["isPreRelease"]
        summary = self.summary.call_args.args[0]
        assert "### Patch list" not in summary
        assert "Incomplete Apps" in summary

    def test_invalid_dev_is_suppressed_when_main_is_valid(self, capsys) -> None:
        self.add_target(patches=[self.app_patch("Main patch")])
        self.add_target(branch="dev", patches=[])
        catalog = self.run_update()
        assert "https://github.com/owner/alpha" not in capsys.readouterr().out
        assert catalog["bundles"][0]["patches"][0]["name"] == "Main patch"
        assert "isPreRelease" not in catalog["bundles"][0]
        assert "### Patch list" not in self.summary.call_args.args[0]

    def test_identical_invalid_branches_have_one_summary_entry(self) -> None:
        self.add_target().write_text("{broken", encoding="utf-8")
        self.add_target(branch="dev").write_text("[]", encoding="utf-8")
        repos_snapshot = self.repos_path.read_bytes()
        assert self.run_update()["bundles"] == []
        summary = self.summary.call_args.args[0]
        assert "### Patch list (1)" in summary
        assert "https://github.com/owner/alpha: Invalid data" in summary
        assert "(main)" not in summary
        assert "(dev)" not in summary
        assert summary.count("- https://") == 1
        assert self.repos_path.read_bytes() == repos_snapshot

    def test_different_invalid_branches_share_one_repository_entry(self) -> None:
        self.add_target(patches=[])
        self.add_target(branch="dev").write_text("{broken", encoding="utf-8")
        assert self.run_update()["bundles"] == []
        summary = self.summary.call_args.args[0]
        assert "### Patch list (1)" in summary
        assert (
            "https://github.com/owner/alpha: (main) No patches found; (dev) Invalid data"
            in summary
        )
        assert summary.count("- https://") == 1

    @pytest.mark.parametrize(
        "invalid_branch,skipped_branch", (("main", "dev"), ("dev", "main"))
    )
    def test_null_sha_does_not_hide_other_branch_errors_or_use_stale_files(
        self, invalid_branch, skipped_branch
    ) -> None:
        self.add_target(branch=invalid_branch, patches=[])
        skipped_patch_path = self.add_target(branch=skipped_branch, sha=None)
        skipped_bundle_path = (
            self.bundles_dir / f"github~owner~alpha~{skipped_branch}.json"
        )
        with patch.object(local_data, "load_json", wraps=load_json) as read_local:
            assert self.run_update()["bundles"] == []
        read_paths = [call.args[0] for call in read_local.call_args_list]
        assert skipped_patch_path not in read_paths
        assert skipped_bundle_path not in read_paths
        summary = self.summary.call_args.args[0]
        assert "### Patch list (1)" in summary
        assert (
            f"https://github.com/owner/alpha: ({invalid_branch}) No patches found"
            in summary
        )
        assert f"({skipped_branch})" not in summary

    def test_main_is_selected_when_newer_than_dev(self) -> None:
        self.add_target(
            timestamp=BUNDLE_TIME_MS + 1, patches=[self.app_patch("Main patch")]
        )
        self.add_target(branch="dev", patches=[self.app_patch("Dev patch")])
        assert self.run_update()["bundles"][0]["patches"][0]["name"] == "Main patch"

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
        assert {bundle["source"] for bundle in catalog["bundles"]} == {
            "github",
            "gitlab",
        }
        assert len(catalog["bundles"]) == 2
        assert self.summary.call_args.args[0].startswith("## 🔄 Update (2/2):")

    def test_compatibility_is_deduplicated_once_without_changing_public_schema(
        self,
    ) -> None:
        self.add_target(
            patches=[self.app_patch("Alpha patch"), {"name": "Universal patch"}]
        )
        self.add_target(repo="owner/beta", patches=[self.app_patch("Beta patch")])
        catalog = self.run_update()
        assert catalog["compatibilities"] == [
            [{"packageName": "com.test.app", "targets": [{"version": "1.0"}]}]
        ]
        for bundle in catalog["bundles"]:
            for patch_data in bundle["patches"]:
                assert "compatiblePackages" not in patch_data
                if patch_data["name"] == "Universal patch":
                    assert "compatiblePackagesKey" not in patch_data
                else:
                    assert patch_data["compatiblePackagesKey"] == 0
        assert PACKAGE_UNIVERSAL in catalog["bundles"][0]["appFirstSeen"]

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
        assert catalog["bundles"][0]["stars"] == 17
        assert catalog["bundles"][0]["avatarUrl"] == "https://example.com/cached.png"
        assert catalog["bundles"][0]["repoDescription"] == "Cached repo"
        self.fetch_repo.assert_not_called()
        assert "Repository metadata" not in self.summary.call_args.args[0]

    def test_incomplete_apps_alone_are_grouped_under_update(self, capsys) -> None:
        self.add_target()
        self.run_update()
        self.summary.assert_called_once()
        summary = self.summary.call_args.args[0]
        assert summary.startswith("## 🔄 Update (1/1):\n\n")
        assert "### Incomplete Apps (1)\n\n" in summary
        assert "### Patch list" not in summary
        assert "### Repository metadata" not in summary
        console = capsys.readouterr().out
        assert "Incomplete apps: 1" in console
        assert "com.test.app" not in console

    def test_archived_repository_keeps_catalog_flag_without_duplicate_warning(
        self,
    ) -> None:
        self.add_target()
        repos = load_json(self.repos_path)
        repos["https://github.com/owner/alpha"]["isArchived"] = True
        save_json(self.repos_path, repos)
        catalog = self.run_update()
        assert catalog["bundles"][0]["isArchived"]
        assert "Repository metadata" not in self.summary.call_args.args[0]

    @pytest.mark.parametrize("mode", ("default", "daily", "weekly"))
    def test_modes_keep_metadata_refresh_and_official_store_priority(
        self, mode
    ) -> None:
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
        save_json(self.public_path, existing_catalog)
        self.fetch_repo.reset_mock()
        self.fetch_app.reset_mock()
        catalog = self.run_update(mode)
        assert self.fetch_repo.call_count == 0
        assert self.fetch_app.call_count == (1 if mode == "weekly" else 0)
        assert catalog["store"]["com.test.app"]["name"] == "Official app"
        assert catalog["bundles"][0]["firstSeen"] == FIRST_SEEN_MS
        assert catalog["bundles"][0]["isOfficial"]

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
        assert catalog["bundles"][0]["repo"] == "owner/renamed"
        assert catalog["bundles"][0]["firstSeen"] == FIRST_SEEN_MS
        assert load_json(self.history_path) == {
            "https://github.com/owner/renamed": old_history
        }
        assert set(load_json(self.hashes_path)) == {"https://github.com/owner/renamed"}
        assert set(load_json(self.repos_path)) == {"https://github.com/owner/renamed"}
        assert not load_json(self.custom_path)["https://github.com/owner/alpha"][
            "enabled"
        ]
        assert (
            "renamedTo"
            not in load_json(self.repos_path)["https://github.com/owner/renamed"]
        )
        assert (self.bundles_dir / "github~owner~renamed~main.json").is_file()
        assert (self.patches_dir / "github~owner~renamed~main.json").is_file()

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
        assert [bundle["repo"] for bundle in catalog["bundles"]] == ["owner/beta"]
        assert set(catalog["store"]) == {"com.beta.app"}
        assert set(load_json(self.hashes_path)) == {"https://github.com/owner/beta"}
        assert load_json(self.history_path) == {
            "https://github.com/owner/beta": {"com.beta.app": ["Patch"]}
        }
        assert [call.args[0] for call in self.fetch_app.call_args_list] == [
            "com.beta.app"
        ]
        assert catalog["compatibilities"][0][0]["packageName"] == "com.beta.app"
        assert self.summary.call_args.args[0].startswith("## 🔄 Update (2/2):")

    def test_counts_only_repositories_with_hashes_and_deduplicates_sources(
        self,
    ) -> None:
        self.add_target()
        self.add_target(source="gitlab", branch="dev")
        self.add_target(repo="owner/invalid", patches=[])
        self.add_target(repo="owner/skipped", sha=None)
        catalog = self.run_update()
        assert len(catalog["bundles"]) == 2
        assert self.summary.call_args.args[0].startswith("## 🔄 Update (2/3):")

    def test_empty_repository_list_still_reports_zero_counts(self) -> None:
        assert self.run_update()["bundles"] == []
        assert self.summary.call_args.args[0] == "## 🔄 Update (0/0):"
        self.fetch_repo.assert_not_called()
        self.fetch_app.assert_not_called()

    def test_default_update_does_not_advance_history_before_daily(self) -> None:
        self.add_target()
        self.run_update()
        assert load_json(self.history_path) == {}
        assert load_json(self.changelog_path) == []
        self.output.assert_not_called()
        with patch.object(
            whats_new,
            "load_json",
            side_effect=lambda path, default: (
                load_json(path, default)
                if path == self.changelog_path
                else pytest.fail("What's New must not reload the catalog or history")
            ),
        ):
            self.run_update("daily")
        repo_url = "https://github.com/owner/alpha"
        assert load_json(self.history_path) == {repo_url: {"com.test.app": ["Patch"]}}
        assert load_json(self.changelog_path)[0]["bundles"][repo_url]["isNew"]
        assert self.markdown_path.is_file()
        self.output.assert_called_once_with("success", "true")

    @pytest.mark.parametrize("mode", ("default", "daily", "weekly"))
    def test_unavailable_and_invalid_bundles_keep_history_without_being_published(
        self, mode
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
        catalog = self.run_update(mode)
        assert catalog["bundles"] == []
        assert "com.old.app" not in catalog["store"]
        assert load_json(self.history_path) == saved_history
        assert load_json(self.changelog_path) == []

    def test_returning_bundle_only_announces_added_patches(self) -> None:
        repo_url = "https://github.com/owner/alpha"
        save_json(self.history_path, {repo_url: {"com.test.app": ["Patch"]}})
        self.add_target(sha=None)
        self.run_update("daily")
        self.add_target()
        self.run_update("daily")
        assert load_json(self.changelog_path) == []
        self.add_target(patches=[self.app_patch(), self.app_patch(name="Added patch")])
        self.run_update("daily")
        changes = load_json(self.changelog_path)[0]["bundles"][repo_url]
        assert "isNew" not in changes
        assert changes["apps"] == {"com.test.app": {"patches": ["Added patch"]}}

    def test_known_app_in_new_bundle_is_not_a_new_app_in_telegram(self) -> None:
        old_url = "https://github.com/owner/unavailable"
        save_json(self.history_path, {old_url: {"com.test.app": ["Patch"]}})
        self.add_target()
        self.run_update("daily")
        assert old_url in load_json(self.history_path)
        markdown = self.markdown_path.read_text(encoding="utf-8")
        assert "📦 (✨New)" in markdown
        assert "📱 (✨New)" not in markdown

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
        assert "isNew" not in changes
        assert changes["apps"] == {
            "com.test.app": {"patches": ["Patch"], "isNew": True}
        }
        markdown = self.markdown_path.read_text(encoding="utf-8")
        assert "📱 (✨New)" not in markdown
        assert "📦 (✨New)" not in markdown
        assert "com.test.app" in markdown

    def test_unchanged_daily_removes_the_previous_notification(self) -> None:
        self.add_target()
        self.run_update("daily")
        history = self.history_path.read_bytes()
        changelog = self.changelog_path.read_bytes()
        assert self.markdown_path.exists()
        self.run_update("daily")
        assert not self.markdown_path.exists()
        assert self.history_path.read_bytes() == history
        assert self.changelog_path.read_bytes() == changelog

    def test_same_day_skip_preserves_baseline_and_removes_stale_notification(
        self,
    ) -> None:
        self.add_target()
        self.run_update("daily")
        history = self.history_path.read_bytes()
        changelog = self.changelog_path.read_bytes()
        assert self.markdown_path.exists()
        self.add_target(patches=[self.app_patch(name="Next patch")])
        self.run_update("daily")
        assert self.history_path.read_bytes() == history
        assert self.changelog_path.read_bytes() == changelog
        assert not self.markdown_path.exists()
        self.clock.now.return_value += timedelta(days=1)
        self.run_update("daily")
        changes = load_json(self.changelog_path)[0]["bundles"]
        assert changes["https://github.com/owner/alpha"]["apps"] == {
            "com.test.app": {"patches": ["Next patch"]}
        }

    def test_changelog_failure_does_not_mark_update_successful_or_advance_history(
        self,
    ) -> None:
        self.add_target()
        with (
            patch.object(
                whats_new, "generate", side_effect=OSError("Cannot write changelog")
            ),
            pytest.raises(OSError),
        ):
            self.run_update("daily")
        self.output.assert_not_called()
        assert load_json(self.history_path) == {}

    @pytest.mark.parametrize("failure_stage", ("process", "fetch_app_details"))
    def test_failure_before_final_output_does_not_write_state_or_cleanup_files(
        self,
        failure_stage,
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
                failure_stage,
                side_effect=RuntimeError("Unexpected processing failure"),
            ),
            pytest.raises(RuntimeError),
        ):
            self.run_update("daily")
        assert self.snapshot() == snapshot
        assert orphan_file.exists()

    def test_successful_update_cleans_orphans_after_catalog_write(self) -> None:
        self.add_target()
        orphan_file = self.patches_dir / "orphan.json"
        save_json(orphan_file, {})

        def write_output(path: Path, data: dict) -> None:
            if path == self.public_path:
                assert orphan_file.exists()
            save_json(path, data)

        with patch.object(bundle_update, "save_json", side_effect=write_output):
            self.run_update()
        assert not orphan_file.exists()

    def test_local_processing_keeps_state_and_orphans_until_final_update(self) -> None:
        self.add_target()
        orphan_file = self.patches_dir / "orphan.json"
        save_json(orphan_file, {})
        snapshot = self.snapshot()
        sources = {"https://github.com/owner/alpha": {"repo": "owner/alpha"}}
        local_hashes = local_data.process(sources, {}, load_json(self.repos_path), {})
        assert set(local_hashes) == {"https://github.com/owner/alpha"}
        assert (
            "compatiblePackages"
            in sources["https://github.com/owner/alpha"]["patches"][0]
        )
        assert (
            "compatiblePackagesKey"
            not in sources["https://github.com/owner/alpha"]["patches"][0]
        )
        assert self.snapshot() == snapshot
        assert orphan_file.exists()

    def test_app_name_comes_from_selected_branch(self) -> None:
        main = self.app_patch()
        main["compatiblePackages"][0]["name"] = "Stable app"
        dev = self.app_patch()
        dev["compatiblePackages"][0]["name"] = "Dev app"
        self.add_target(timestamp=BUNDLE_TIME_MS + 1, patches=[main])
        self.add_target(branch="dev", patches=[dev])
        assert self.run_update()["store"]["com.test.app"]["name"] == "Stable app"

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
        assert bundles["github"]["isOfficial"]
        assert "isOfficial" not in bundles["gitlab"]
        assert bundles["github"]["stars"] == 100
        assert bundles["gitlab"]["stars"] == 5

    def test_rename_preserves_other_host_and_keeps_new_files_readable(self) -> None:
        self.add_target()
        self.add_target(source="gitlab")
        repos = load_json(self.repos_path)
        repos["https://github.com/owner/alpha"]["renamedTo"] = (
            "https://github.com/owner/new"
        )
        save_json(self.repos_path, repos)
        catalog = self.run_update()
        assert {
            (bundle["source"], bundle["repo"]) for bundle in catalog["bundles"]
        } == {("github", "owner/new"), ("gitlab", "owner/alpha")}
        assert "https://gitlab.com/owner/alpha" in load_json(self.repos_path)
        assert self.run_update() == catalog


@pytest.mark.parametrize(
    "error",
    (
        URLError("DNS failed"),
        HTTPException("Connection closed"),
        ExtraHTTPError("HTTP 503"),
        ValueError("Invalid JSON"),
    ),
)
def test_google_play_request_failure_preserves_saved_app_and_updates_other_apps(
    tmp_path: Path,
    error: Exception,
) -> None:
    saved_app = {"name": "Saved app", "minInstalls": 100, "category": "Tools"}
    apps = {"com.test.failed": dict(saved_app), "com.test.working": {}}

    def fetch_app(package_name: str, **_kwargs: object) -> dict:
        if package_name == "com.test.failed":
            raise error
        return {"title": "Working app"}

    with (
        patch.object(gplay_scrape, "gplay_app", side_effect=fetch_app),
        patch.object(gplay_scrape, "OFFICIAL_BUNDLES_PATH", tmp_path / "official.json"),
    ):
        gplay_scrape.process(apps, "weekly")

    assert apps["com.test.failed"] == saved_app
    assert apps["com.test.working"]["name"] == "Working app"


@pytest.mark.parametrize("mode", ("default", "daily", "weekly"))
def test_universal_skips_google_play_and_keeps_official_metadata(mode) -> None:
    apps = {PACKAGE_UNIVERSAL: {"name": "Saved universal"}, "com.test.app": {}}
    official = {
        "store": {
            PACKAGE_UNIVERSAL: {
                "name": "Universal patches",
                "description": "Works with every app",
                "iconUrl": "https://example.com/universal.png",
            }
        }
    }
    with (
        patch.object(gplay_scrape, "load_json", return_value=official),
        patch.object(
            gplay_scrape,
            "fetch_app_details",
            return_value=({"name": "Real app"}, False),
        ) as request,
    ):
        gplay_scrape.process(apps, mode)
    request.assert_called_once_with("com.test.app")
    assert apps[PACKAGE_UNIVERSAL] == official["store"][PACKAGE_UNIVERSAL]
    assert apps["com.test.app"]["name"] == "Real app"
