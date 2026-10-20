from http.client import HTTPException
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

import discover
from common.utils import load_json, save_json
from discovery import audit_readme, find_projects, jman, morphe_archive, official


class TestDiscover:
    @pytest.fixture(autouse=True)
    def prepare(self, tmp_path: Path, patch_context, block_network) -> None:
        self.patch_context = patch_context
        self.root = tmp_path
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
            self.patch_context.enter_context(output_patcher)
        for patcher in (
            patch.multiple(
                discover,
                DISCOVER_DIR=self.discover_dir,
                REPOS_JSON_PATH=self.repos_path,
                ROOT_DIR=self.root,
            ),
            patch.object(official, "OFFICIAL_BUNDLES_PATH", self.official_path),
        ):
            self.patch_context.enter_context(patcher)
        self.summary = self.patch_context.enter_context(
            patch.object(discover, "append_step_summary")
        )
        self.open_url = block_network

    @pytest.mark.parametrize("module", discover.PROVIDER_MODULES)
    @pytest.mark.parametrize("status", (404, 451, 503, 418))
    def test_http_errors_report_actual_code_and_preserve_saved_files(
        self, module, status
    ) -> None:
        snapshot = self.official_path.read_bytes()
        saved_file = module.OUTPUT_PATH.read_bytes()
        error = HTTPError("https://example.com", status, "Failed", None, None)
        self.patch_context.callback(error.close)
        self.open_url.side_effect = error
        assert (
            module.discover()
            == f"[{module.OUTPUT_PATH.stem}]: Request failed (HTTP {status}); kept saved sources"
        )
        assert module.OUTPUT_PATH.read_bytes() == saved_file
        assert self.official_path.read_bytes() == snapshot

    @pytest.mark.parametrize("module", discover.PROVIDER_MODULES)
    @pytest.mark.parametrize(
        "error",
        (
            URLError("DNS lookup failed"),
            TimeoutError("timed out"),
            HTTPException("connection closed"),
        ),
    )
    def test_request_errors_use_exception_reason(self, module, error) -> None:
        self.open_url.side_effect = error
        reason = error.reason if isinstance(error, URLError) else str(error)
        assert (
            module.discover()
            == f"[{module.OUTPUT_PATH.stem}]: Request failed: {reason}; kept saved sources"
        )
        assert load_json(module.OUTPUT_PATH) == self.saved_sources

    @pytest.mark.parametrize("module", (official, jman))
    @pytest.mark.parametrize("content", (b"{broken", b"\xff"))
    def test_unreadable_json_is_invalid_provider_data(self, module, content) -> None:
        snapshot = self.official_path.read_bytes()
        self.open_url.side_effect = None
        self.open_url.return_value.__enter__.return_value.read.return_value = content
        assert (
            module.discover()
            == f"[{module.OUTPUT_PATH.stem}]: Invalid provider data; kept saved sources"
        )
        assert load_json(module.OUTPUT_PATH) == self.saved_sources
        assert self.official_path.read_bytes() == snapshot

    @pytest.mark.parametrize(
        "module,data",
        [
            (module, data)
            for module, invalid_data in (
                (official, [None, [], {}, {"bundles": {}}]),
                (jman, [None, [], "unexpected"]),
            )
            for data in invalid_data
        ],
    )
    def test_invalid_json_structure_preserves_saved_sources_and_snapshot(
        self, module, data
    ) -> None:
        snapshot = self.official_path.read_bytes()
        with patch.object(module, "fetch", return_value=data):
            assert "Invalid provider data" in module.discover()
        assert load_json(module.OUTPUT_PATH) == self.saved_sources
        assert self.official_path.read_bytes() == snapshot

    @pytest.mark.parametrize(
        "module,data",
        (
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
        ),
    )
    def test_empty_results_preserve_saved_sources_and_official_snapshot(
        self, module, data
    ) -> None:
        snapshot = self.official_path.read_bytes()
        with patch.object(module, "fetch", return_value=data):
            assert (
                module.discover()
                == f"[{module.OUTPUT_PATH.stem}]: No sources found; kept saved sources"
            )
        assert load_json(module.OUTPUT_PATH) == self.saved_sources
        assert self.official_path.read_bytes() == snapshot

    @pytest.mark.parametrize(
        "content", (None, b"{}", b"[]", b"{broken", b"\xff", b'{"url": 1}')
    )
    def test_warning_does_not_claim_unusable_saved_sources_are_available(
        self, content
    ) -> None:
        if content is None:
            official.OUTPUT_PATH.unlink()
        else:
            official.OUTPUT_PATH.write_bytes(content)
        with patch.object(official, "fetch", return_value={"bundles": []}):
            assert (
                official.discover()
                == "[official]: No sources found; no saved sources available"
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
            assert official.discover() is None
        assert load_json(self.official_path) == data
        assert load_json(official.OUTPUT_PATH) == {
            "https://github.com/owner/new": {},
            "https://gitlab.com/group/project": {},
        }

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
            assert jman.discover() is None
        assert load_json(jman.OUTPUT_PATH) == {"https://github.com/owner/new": {}}

    def test_archive_extracts_and_deduplicates_source_links(self) -> None:
        content = "\n".join(
            [
                "[GitHub](https://morphe.software/add-source?github=owner/new)",
                "[Duplicate](https://morphe.software/add-source?github=owner/new)",
                "[GitLab](https://morphe.software/add-source?gitlab=group/project)",
            ]
        )
        with patch.object(morphe_archive, "fetch", return_value=content):
            assert morphe_archive.discover() is None
        assert load_json(morphe_archive.OUTPUT_PATH) == {
            "https://github.com/owner/new": {},
            "https://gitlab.com/group/project": {},
        }

    def test_main_uses_saved_sources_and_reports_each_failed_provider_once(
        self,
    ) -> None:
        self.open_url.side_effect = URLError("offline")
        assert discover.main([]) == 0
        assert load_json(self.repos_path) == self.saved_repos
        self.summary.assert_called_once()
        summary = self.summary.call_args.args[0]
        assert summary.startswith("## 🔎 Discovery:\n\n")
        for provider in ("official", "jman", "morphe-archive"):
            assert summary.count(f"[{provider}]:") == 1
        assert "no saved sources available" not in summary

    def test_main_stops_without_changing_repos_when_no_sources_are_usable(self) -> None:
        for module in discover.PROVIDER_MODULES:
            module.OUTPUT_PATH.write_text("[]", encoding="utf-8")
        snapshot = self.repos_path.read_bytes()
        self.open_url.side_effect = URLError("offline")
        assert discover.main([]) == 1
        assert self.repos_path.read_bytes() == snapshot
        self.summary.assert_called_once()
        summary = self.summary.call_args.args[0]
        assert "No usable provider files found; discovery stopped" in summary
        assert summary.count("no saved sources available") == len(
            discover.PROVIDER_MODULES
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
            assert discover.main([]) == 0
        assert load_json(self.repos_path) == self.saved_repos
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
            pytest.raises(OSError, match="disk full"),
        ):
            official.discover()
        assert self.official_path.read_bytes() == snapshot
        assert official.OUTPUT_PATH.read_bytes() == sources
        with (
            patch.object(
                morphe_archive,
                "fetch",
                return_value="https://morphe.software/add-source?github=owner/new",
            ),
            patch("discovery.save_json", side_effect=OSError("disk full")),
            pytest.raises(OSError, match="disk full"),
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
            pytest.raises(RuntimeError, match="Unexpected failure"),
        ):
            discover.main([])
        assert self.repos_path.read_bytes() == snapshot
        self.summary.assert_not_called()

    def test_default_does_not_audit_or_search_projects(self) -> None:
        self.open_url.side_effect = URLError("offline")
        with (
            patch.object(audit_readme, "audit_repos_and_links") as audit,
            patch.object(find_projects, "run") as search,
        ):
            assert discover.main([]) == 0
        audit.assert_not_called()
        search.assert_not_called()

    @pytest.mark.parametrize("mode", ("--daily", "--weekly"))
    def test_daily_and_weekly_combine_audit_and_project_reports(self, mode) -> None:
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

        with (
            patch.object(
                audit_readme,
                "load_lines",
                side_effect=[["https://github.com/owner/archived"], []],
            ),
            patch.object(
                audit_readme, "fetch_repo_details", return_value={"is_archived": True}
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
            patch.object(find_projects, "check_link_status", side_effect=link_status),
        ):
            self.open_url.side_effect = URLError("offline")
            self.summary.reset_mock()
            assert discover.main([mode]) == 0
            search.assert_called_once()
            self.summary.assert_called_once()
            summary = self.summary.call_args.args[0]
            assert summary.count("## 🔎 Discovery:") == 1
            assert "### Bundle sources" in summary
            assert "### README audit" in summary
            assert "Repository is archived" in summary
            assert "### New projects" in summary
            assert "### New projects (1)" in summary
            assert "New Repositories Found" not in summary
            assert "<details>" not in summary
            assert "## 📋" not in summary
            assert "## 🔍" not in summary
            assert (
                output_path.read_text(encoding="utf-8") == repository["html_url"] + "\n"
            )
            assert load_json(self.repos_path) == self.saved_repos

    def test_extended_discovery_stops_when_no_bundle_sources_are_usable(self) -> None:
        for module in discover.PROVIDER_MODULES:
            module.OUTPUT_PATH.write_text("[]", encoding="utf-8")
        self.open_url.side_effect = URLError("offline")
        with (
            patch.object(audit_readme, "audit_repos_and_links") as audit,
            patch.object(find_projects, "run") as search,
        ):
            assert discover.main(["--daily"]) == 1
        audit.assert_not_called()
        search.assert_not_called()
        assert load_json(self.repos_path) == self.saved_repos


def test_sync_keeps_hosts_independent_and_preserves_saved_fields() -> None:
    github = "https://github.com/owner/repo"
    gitlab = "https://gitlab.com/owner/repo"
    saved = {
        github: {"main": "sha", "stars": 2, "renamedTo": "https://github.com/owner/new"}
    }
    actual = discover._sync_repos({github.upper(): {}, gitlab: {}}, saved)
    assert actual[github] == saved[github]
    assert actual[gitlab] == {}
    assert len(actual) == 2
