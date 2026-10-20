import tempfile
import unittest
from http.client import HTTPException
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import discover
from common.utils import load_json, save_json
from discovery import audit_readme, find_projects, jman, morphe_archive, official


class DiscoverTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.root = Path(temporary_directory.name)
        self.discover_dir = self.root / "discover"
        self.repos_path = self.root / "repos.json"
        self.official_path = self.root / "official-bundles.json"
        self.saved_sources = {"https://github.com/owner/saved": {}}
        self.saved_repos = {
            "https://github.com/owner/saved": {
                "name": "Saved bundle",
                "main": "saved-sha",
                "dev": None,
                "image": "image-sha",
            }
        }
        save_json(self.repos_path, self.saved_repos)
        save_json(self.official_path, {"bundles": [], "store": {"saved": {}}})
        for module in discover.PROVIDER_MODULES:
            output_path = self.discover_dir / module.OUTPUT_PATH.name
            save_json(output_path, self.saved_sources)
            output_patcher = patch.object(module, "OUTPUT_PATH", output_path)
            output_patcher.start()
            self.addCleanup(output_patcher.stop)
        for patcher in (
            patch.multiple(
                discover,
                DISCOVER_DIR=self.discover_dir,
                REPOS_JSON_PATH=self.repos_path,
                ROOT_DIR=self.root,
            ),
            patch.object(official, "OFFICIAL_BUNDLES_PATH", self.official_path),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        summary_patcher = patch.object(discover, "append_step_summary")
        self.summary = summary_patcher.start()
        self.addCleanup(summary_patcher.stop)
        network_patcher = patch(
            "urllib.request.urlopen",
            side_effect=AssertionError("Unexpected network access"),
        )
        self.open_url = network_patcher.start()
        self.addCleanup(network_patcher.stop)

    def test_http_errors_report_actual_code_and_preserve_saved_files(self) -> None:
        snapshot = self.official_path.read_bytes()
        for module in discover.PROVIDER_MODULES:
            saved_file = module.OUTPUT_PATH.read_bytes()
            for status in (404, 451, 503, 418):
                with self.subTest(provider=module.OUTPUT_PATH.stem, status=status):
                    error = HTTPError(
                        "https://example.com", status, "Failed", None, None
                    )
                    self.addCleanup(error.close)
                    self.open_url.side_effect = error
                    self.assertEqual(
                        module.discover(),
                        f"[{module.OUTPUT_PATH.stem}]: Request failed (HTTP {status}); kept saved sources",
                    )
                    self.assertEqual(module.OUTPUT_PATH.read_bytes(), saved_file)
                    self.assertEqual(self.official_path.read_bytes(), snapshot)

    def test_request_errors_use_exception_reason(self) -> None:
        for module in discover.PROVIDER_MODULES:
            for error in (
                URLError("DNS lookup failed"),
                TimeoutError("timed out"),
                HTTPException("connection closed"),
            ):
                with self.subTest(provider=module.OUTPUT_PATH.stem, error=error):
                    self.open_url.side_effect = error
                    reason = error.reason if isinstance(error, URLError) else str(error)
                    self.assertEqual(
                        module.discover(),
                        f"[{module.OUTPUT_PATH.stem}]: Request failed: {reason}; kept saved sources",
                    )
                    self.assertEqual(load_json(module.OUTPUT_PATH), self.saved_sources)

    def test_unreadable_json_is_invalid_provider_data(self) -> None:
        snapshot = self.official_path.read_bytes()
        self.open_url.side_effect = None
        for module in (official, jman):
            for content in (b"{broken", b"\xff"):
                with self.subTest(provider=module.OUTPUT_PATH.stem, content=content):
                    self.open_url.return_value.__enter__.return_value.read.return_value = content
                    self.assertEqual(
                        module.discover(),
                        f"[{module.OUTPUT_PATH.stem}]: Invalid provider data; kept saved sources",
                    )
                    self.assertEqual(load_json(module.OUTPUT_PATH), self.saved_sources)
                    self.assertEqual(self.official_path.read_bytes(), snapshot)

    def test_invalid_json_structure_preserves_saved_sources_and_snapshot(self) -> None:
        snapshot = self.official_path.read_bytes()
        for module, invalid_data in (
            (official, [None, [], {}, {"bundles": {}}]),
            (jman, [None, [], "unexpected"]),
        ):
            for data in invalid_data:
                with self.subTest(provider=module.OUTPUT_PATH.stem, data=data):
                    with patch.object(module, "fetch", return_value=data):
                        self.assertIn("Invalid provider data", module.discover())
                    self.assertEqual(load_json(module.OUTPUT_PATH), self.saved_sources)
                    self.assertEqual(self.official_path.read_bytes(), snapshot)

    def test_empty_results_preserve_saved_sources_and_official_snapshot(self) -> None:
        snapshot = self.official_path.read_bytes()
        for module, data in (
            (official, {"bundles": []}),
            (
                jman,
                {
                    "disabled": {
                        "disabled": True,
                        "patches": "https://github.com/owner/new",
                    }
                },
            ),
            (morphe_archive, "README without source links"),
        ):
            with self.subTest(provider=module.OUTPUT_PATH.stem):
                with patch.object(module, "fetch", return_value=data):
                    self.assertEqual(
                        module.discover(),
                        f"[{module.OUTPUT_PATH.stem}]: No sources found; kept saved sources",
                    )
                self.assertEqual(load_json(module.OUTPUT_PATH), self.saved_sources)
                self.assertEqual(self.official_path.read_bytes(), snapshot)

    def test_warning_does_not_claim_unusable_saved_sources_are_available(self) -> None:
        for content in (None, b"{}", b"[]", b"{broken", b"\xff", b'{"url": 1}'):
            with self.subTest(content=content):
                if content is None:
                    official.OUTPUT_PATH.unlink()
                else:
                    official.OUTPUT_PATH.write_bytes(content)
                with patch.object(official, "fetch", return_value={"bundles": []}):
                    self.assertEqual(
                        official.discover(),
                        "[official]: No sources found; no saved sources available",
                    )

    def test_official_success_updates_sources_and_complete_snapshot(self) -> None:
        data = {
            "bundles": [
                {"source": "github", "repo": "owner/new"},
                {"source": "gitlab", "repo": "group/project"},
            ],
            "store": {"com.test.app": {"name": "Test app"}},
        }
        with patch.object(official, "fetch", return_value=data):
            self.assertIsNone(official.discover())
        self.assertEqual(load_json(self.official_path), data)
        self.assertEqual(
            load_json(official.OUTPUT_PATH),
            {
                "https://github.com/owner/new": {},
                "https://gitlab.com/group/project": {},
            },
        )

    def test_jman_keeps_enabled_usable_sources(self) -> None:
        data = {
            "enabled": {"patches": "https://github.com/owner/new/releases/bundle.mpp"},
            "disabled": {
                "disabled": True,
                "patches": "https://github.com/owner/disabled",
            },
            "unrelated": {"patches": "https://example.com/bundle.mpp"},
            "invalid": {"patches": 7},
            "other": "ignored",
        }
        with patch.object(jman, "fetch", return_value=data):
            self.assertIsNone(jman.discover())
        self.assertEqual(
            load_json(jman.OUTPUT_PATH), {"https://github.com/owner/new": {}}
        )

    def test_archive_extracts_and_deduplicates_source_links(self) -> None:
        content = "\n".join(
            [
                "[GitHub](https://morphe.software/add-source?github=owner/new)",
                "[Duplicate](https://morphe.software/add-source?github=owner/new)",
                "[GitLab](https://morphe.software/add-source?gitlab=group/project)",
            ]
        )
        with patch.object(morphe_archive, "fetch", return_value=content):
            self.assertIsNone(morphe_archive.discover())
        self.assertEqual(
            load_json(morphe_archive.OUTPUT_PATH),
            {
                "https://github.com/owner/new": {},
                "https://gitlab.com/group/project": {},
            },
        )

    def test_main_uses_saved_sources_and_reports_each_failed_provider_once(
        self,
    ) -> None:
        self.open_url.side_effect = URLError("offline")
        self.assertEqual(discover.main([]), 0)
        self.assertEqual(load_json(self.repos_path), self.saved_repos)
        self.summary.assert_called_once()
        summary = self.summary.call_args.args[0]
        self.assertTrue(summary.startswith("## 🔎 Discovery:\n\n"))
        for provider in ("official", "jman", "morphe-archive"):
            self.assertEqual(summary.count(f"[{provider}]:"), 1)
        self.assertNotIn("no saved sources available", summary)

    def test_main_stops_without_changing_repos_when_no_sources_are_usable(self) -> None:
        for module in discover.PROVIDER_MODULES:
            module.OUTPUT_PATH.write_text("[]", encoding="utf-8")
        snapshot = self.repos_path.read_bytes()
        self.open_url.side_effect = URLError("offline")
        self.assertEqual(discover.main([]), 1)
        self.assertEqual(self.repos_path.read_bytes(), snapshot)
        self.summary.assert_called_once()
        summary = self.summary.call_args.args[0]
        self.assertIn("No usable provider files found; discovery stopped", summary)
        self.assertEqual(
            summary.count("no saved sources available"), len(discover.PROVIDER_MODULES)
        )

    def test_main_preserves_custom_exclusions_and_existing_repo_state(self) -> None:
        save_json(
            self.discover_dir / "custom.json",
            {"https://github.com/owner/disabled": {"enabled": False}},
        )
        data = {
            "bundles": [
                {"source": "github", "repo": "owner/disabled"},
                {"source": "github", "repo": "OWNER/SAVED"},
            ]
        }
        with (
            patch.object(official, "fetch", return_value=data),
            patch.object(
                jman,
                "fetch",
                return_value={"saved": {"patches": "https://github.com/owner/saved"}},
            ),
            patch.object(
                morphe_archive,
                "fetch",
                return_value="https://morphe.software/add-source?github=owner/saved",
            ),
        ):
            self.assertEqual(discover.main([]), 0)
        self.assertEqual(load_json(self.repos_path), self.saved_repos)
        self.summary.assert_not_called()

    def test_snapshot_and_provider_write_failures_propagate(self) -> None:
        snapshot = self.official_path.read_bytes()
        sources = official.OUTPUT_PATH.read_bytes()
        with (
            patch.object(
                official,
                "fetch",
                return_value={"bundles": [{"source": "github", "repo": "owner/new"}]},
            ),
            patch.object(official, "save_json", side_effect=OSError("disk full")),
            self.assertRaisesRegex(OSError, "disk full"),
        ):
            official.discover()
        self.assertEqual(self.official_path.read_bytes(), snapshot)
        self.assertEqual(official.OUTPUT_PATH.read_bytes(), sources)
        with (
            patch.object(
                morphe_archive,
                "fetch",
                return_value="https://morphe.software/add-source?github=owner/new",
            ),
            patch("discovery.save_json", side_effect=OSError("disk full")),
            self.assertRaisesRegex(OSError, "disk full"),
        ):
            morphe_archive.discover()

    def test_unexpected_provider_errors_stop_discovery_without_rewriting_repos(
        self,
    ) -> None:
        snapshot = self.repos_path.read_bytes()
        with (
            patch.object(
                official, "fetch", side_effect=RuntimeError("Unexpected failure")
            ),
            patch.object(jman, "fetch", return_value={}),
            patch.object(morphe_archive, "fetch", return_value=""),
            self.assertRaisesRegex(RuntimeError, "Unexpected failure"),
        ):
            discover.main([])
        self.assertEqual(self.repos_path.read_bytes(), snapshot)
        self.summary.assert_not_called()

    def test_default_does_not_audit_or_search_projects(self) -> None:
        self.open_url.side_effect = URLError("offline")
        with (
            patch.object(audit_readme, "audit_repos_and_links") as audit,
            patch.object(find_projects, "main") as search,
        ):
            self.assertEqual(discover.main([]), 0)
        audit.assert_not_called()
        search.assert_not_called()

    def test_daily_and_weekly_combine_audit_and_project_reports(self) -> None:
        project_dir = self.root / "projects"
        project_dir.mkdir()
        output_path = project_dir / "new-projects.txt"
        repository = {
            "name": "new-project",
            "full_name": "owner/new-project",
            "html_url": "https://github.com/owner/new-project",
            "default_branch": "develop",
            "stargazers_count": 4,
            "created_at": "2026-01-01T00:00:00Z",
            "pushed_at": "2026-10-19T00:00:00Z",
            "description": "A standalone Morphe project",
        }
        bundle = {**repository, "full_name": "owner/patch-bundle"}
        known = {**repository, "full_name": "owner/known-project"}
        excluded = {**repository, "full_name": "owner/excluded-project"}
        no_readme = {**repository, "full_name": "owner/no-readme"}

        def link_status(url: str, **_kwargs: object) -> dict:
            return {
                "is_active": url.endswith(
                    (
                        "owner/new-project/develop/README.md",
                        "owner/patch-bundle/dev/patches-bundle.json",
                    )
                ),
                "is_dead": True,
            }

        for mode in ("--daily", "--weekly"):
            with (
                self.subTest(mode=mode),
                patch.object(
                    audit_readme,
                    "load_lines",
                    side_effect=[["https://github.com/owner/archived"], []],
                ),
                patch.object(
                    audit_readme,
                    "fetch_repo_details",
                    return_value={"is_archived": True},
                ),
                patch.multiple(
                    find_projects,
                    ROOT_DIR=self.root,
                    RAW_SEARCH_PATH=self.root / "raw-search.json",
                    RAW_FILTER_PATH=self.root / "raw-filter.json",
                    PROJECTS_DIR=project_dir,
                    NEW_PROJECTS_PATH=output_path,
                    SEARCH_KEYWORDS=["morphe"],
                    TARGET_USERS=[],
                ),
                patch.object(
                    find_projects,
                    "fetch",
                    return_value={
                        "total_count": 6,
                        "items": [
                            repository,
                            repository,
                            bundle,
                            known,
                            excluded,
                            no_readme,
                        ],
                    },
                ) as search,
                patch.object(
                    find_projects,
                    "load_lines",
                    side_effect=[
                        ["https://github.com/owner/known-project"],
                        ["https://github.com/owner/excluded-project"],
                    ],
                ),
                patch.object(
                    find_projects, "check_link_status", side_effect=link_status
                ),
            ):
                self.open_url.side_effect = URLError("offline")
                self.summary.reset_mock()
                self.assertEqual(discover.main([mode]), 0)
                search.assert_called_once()
                self.summary.assert_called_once()
                summary = self.summary.call_args.args[0]
                self.assertEqual(summary.count("## 🔎 Discovery:"), 1)
                self.assertIn("### Bundle sources", summary)
                self.assertIn("### README audit", summary)
                self.assertIn("Repository is archived", summary)
                self.assertIn("### New projects", summary)
                self.assertIn("### New projects (1)", summary)
                self.assertNotIn("New Repositories Found", summary)
                self.assertNotIn("<details>", summary)
                self.assertNotIn("## 📋", summary)
                self.assertNotIn("## 🔍", summary)
                self.assertEqual(
                    output_path.read_text(encoding="utf-8"),
                    repository["html_url"] + "\n",
                )
                self.assertEqual(load_json(self.repos_path), self.saved_repos)

    def test_project_details_depend_on_verified_project_count(self) -> None:
        for result_count in (9, 10):
            candidates = [
                {
                    "full_name": f"owner/project-{index}",
                    "html_url": f"https://github.com/owner/project-{index}",
                }
                for index in range(result_count + 1)
            ]
            output_path = self.root / "new-projects.txt"
            with (
                self.subTest(result_count=result_count),
                patch.multiple(
                    find_projects,
                    ROOT_DIR=self.root,
                    PROJECTS_DIR=self.root,
                    NEW_PROJECTS_PATH=output_path,
                ),
                patch.object(
                    find_projects,
                    "is_valid_candidate",
                    side_effect=lambda repo, excluded_repo=candidates[-1]: (
                        repo != excluded_repo
                    ),
                ),
            ):
                summary = find_projects.verify_and_export_repos(candidates)
            self.assertTrue(
                summary.startswith(f"### New projects ({result_count})\n\n")
            )
            self.assertEqual("<details>" in summary, result_count >= 10)
            self.assertEqual(summary.count("#### [owner/project-"), result_count)
            self.assertNotIn("New Repositories Found", summary)
            self.assertEqual(len(output_path.read_text().splitlines()), result_count)

    def test_audit_groups_collapse_independently_at_ten_results(self) -> None:
        for result_count in (9, 10):
            with (
                self.subTest(result_count=result_count),
                patch.object(
                    audit_readme,
                    "load_lines",
                    side_effect=[
                        [
                            f"https://github.com/owner/repo-{index}"
                            for index in range(result_count)
                        ],
                        ["https://example.com"],
                    ],
                ),
                patch.object(
                    audit_readme, "fetch_repo_details", return_value={"is_404": True}
                ),
                patch.object(
                    audit_readme, "check_link_status", return_value={"error": "Timeout"}
                ),
            ):
                summary = audit_readme.audit_repos_and_links()
            unavailable, other = summary.split("#### Other Errors (1)")
            self.assertIn(f"#### Unavailable ({result_count})", unavailable)
            self.assertEqual("<details>" in unavailable, result_count >= 10)
            self.assertNotIn("<details>", other)

    def test_extended_discovery_stops_when_no_bundle_sources_are_usable(self) -> None:
        for module in discover.PROVIDER_MODULES:
            module.OUTPUT_PATH.write_text("[]", encoding="utf-8")
        self.open_url.side_effect = URLError("offline")
        with (
            patch.object(audit_readme, "audit_repos_and_links") as audit,
            patch.object(find_projects, "main") as search,
        ):
            self.assertEqual(discover.main(["--daily"]), 1)
        audit.assert_not_called()
        search.assert_not_called()
        self.assertEqual(load_json(self.repos_path), self.saved_repos)

    def test_no_candidates_preserves_saved_project_file_and_reports_result(
        self,
    ) -> None:
        output_path = self.root / "new-projects.txt"
        output_path.write_text(
            "https://github.com/owner/saved-project\n", encoding="utf-8"
        )
        with patch.object(find_projects, "NEW_PROJECTS_PATH", output_path):
            report = find_projects.verify_and_export_repos([])
        self.assertIn("### New projects", report)
        self.assertIn("No new standalone repositories found", report)
        self.assertEqual(
            output_path.read_text(encoding="utf-8"),
            "https://github.com/owner/saved-project\n",
        )


class RepositoryIdentityTests(unittest.TestCase):
    def test_sync_keeps_hosts_independent_and_preserves_saved_fields(self) -> None:
        github = "https://github.com/owner/repo"
        gitlab = "https://gitlab.com/owner/repo"
        saved = {
            github: {
                "main": "sha",
                "stars": 2,
                "renamedTo": "https://github.com/owner/new",
            }
        }
        actual = discover._sync_repos({github.upper(): {}, gitlab: {}}, saved)
        self.assertEqual(actual[github], saved[github])
        self.assertEqual(actual[gitlab], {})
        self.assertEqual(len(actual), 2)


if __name__ == "__main__":
    unittest.main()
