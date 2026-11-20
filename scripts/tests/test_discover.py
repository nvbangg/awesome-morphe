from pathlib import Path
from unittest.mock import patch

import httpx2
import pytest
from pydantic import ValidationError

import discover
from common.files import load_json, save_json
from discovery import audit_readme, find_projects, jman, morphe_archive, official


class TestDiscover:
    @pytest.fixture(autouse=True)
    def prepare(self, tmp_path: Path, patch_context, block_network, http_error) -> None:
        self.patch_context = patch_context
        self.http_error = http_error
        self.root = tmp_path
        self.custom_path = self.root / "custom.json"
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
        save_json(self.official_path, {"bundles": [], "store": {"saved": {}}})
        save_json(self.custom_path, {})
        save_json(
            self.repos_path,
            {
                "repositories": self.saved_repos,
                "providers": {name: list(self.saved_sources) for name in discover.PROVIDER_MODULES},
                "renames": {},
            },
        )
        for patcher in (
            patch.multiple(
                discover,
                CUSTOM_JSON_PATH=self.custom_path,
                REPOS_JSON_PATH=self.repos_path,
                ROOT_DIR=self.root,
            ),
            patch.object(official, "OFFICIAL_BUNDLES_PATH", self.official_path),
        ):
            self.patch_context.enter_context(patcher)
        self.summary = self.patch_context.enter_context(patch.object(discover, "append_step_summary"))
        self.open_url = block_network

    @pytest.mark.parametrize(
        "module,failure_kind",
        ((official, "http"), (jman, "network"), (morphe_archive, "timeout")),
    )
    def test_provider_failure_preserves_saved_sources(self, module, failure_kind) -> None:
        snapshot = self.official_path.read_bytes()
        saved_file = self.repos_path.read_bytes()
        if failure_kind == "http":
            error = self.http_error("https://example.com", 503)
        elif failure_kind == "network":
            error = httpx2.ConnectError("DNS lookup failed")
        else:
            error = httpx2.ReadTimeout("timed out")
        self.open_url.side_effect = error
        assert module.discover() == ([], str(error))
        assert self.repos_path.read_bytes() == saved_file
        assert self.official_path.read_bytes() == snapshot

    @pytest.mark.parametrize("module", (official, jman))
    def test_unreadable_json_preserves_saved_sources(self, module) -> None:
        snapshot = self.official_path.read_bytes()
        self.open_url.side_effect = None
        self.open_url.return_value = httpx2.Response(200, content=b"{broken")
        assert module.discover() == ([], "Invalid provider data")
        assert self.official_path.read_bytes() == snapshot

    @pytest.mark.parametrize("module,data", ((official, {"bundles": {}}), (jman, [])))
    def test_invalid_provider_structure_preserves_saved_sources(self, module, data) -> None:
        snapshot = self.official_path.read_bytes()
        with patch.object(
            module,
            "request",
            return_value=httpx2.Response(200, json=data),
        ):
            assert module.discover() == ([], "Invalid provider data")
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
    def test_empty_results_preserve_saved_sources_and_official_snapshot(self, module, data) -> None:
        snapshot = self.official_path.read_bytes()
        with patch.object(
            module,
            "request",
            return_value=(
                httpx2.Response(200, text=data) if module is morphe_archive else httpx2.Response(200, json=data)
            ),
        ):
            assert module.discover() == ([], None)
        assert self.official_path.read_bytes() == snapshot

    def test_official_success_updates_sources_and_complete_snapshot(self) -> None:
        data = {
            "bundles": [
                {"source": "github", "repo": "owner/new"},
                {"source": "gitlab", "repo": "group/project"},
            ],
            "store": {"com.test.app": {"name": "Test app"}},
        }
        with patch.object(official, "request", return_value=httpx2.Response(200, json=data)):
            sources, error = official.discover()
        assert error is None
        assert load_json(self.official_path) == data
        assert sources == ["https://github.com/owner/new", "https://gitlab.com/group/project"]

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
        with patch.object(jman, "request", return_value=httpx2.Response(200, json=data)):
            assert jman.discover() == (["https://github.com/owner/new"], None)

    def test_archive_extracts_and_deduplicates_source_links(self) -> None:
        content = (
            "[GitHub](https://morphe.software/add-source?github=owner/new)\n"
            "[Duplicate](https://morphe.software/add-source?github=owner/new)\n"
            "[Case variant](https://morphe.software/add-source?github=owner/New)\n"
            "[GitLab](https://morphe.software/add-source?gitlab=group/project)"
        )
        with (
            patch.object(discover, "PROVIDER_MODULES", {"morphe-archive": morphe_archive}),
            patch.object(morphe_archive, "request", return_value=httpx2.Response(200, text=content)) as request,
        ):
            assert discover.main([]) == 0
            saved_repos = self.repos_path.read_bytes()
            request.return_value = httpx2.Response(200, text="\n".join(reversed(content.splitlines())))
            assert discover.main([]) == 0
        assert load_json(self.repos_path)["providers"]["morphe-archive"] == [
            "https://github.com/owner/New",
            "https://github.com/owner/new",
            "https://gitlab.com/group/project",
        ]
        assert self.repos_path.read_bytes() == saved_repos

    def test_provider_outage_keeps_saved_repositories(
        self,
    ) -> None:
        self.open_url.side_effect = httpx2.ConnectError("offline")
        assert discover.main([]) == 0
        assert load_json(self.repos_path)["repositories"] == self.saved_repos

    @pytest.mark.parametrize("arguments", ([], ["--daily"]))
    @pytest.mark.parametrize("content", ("{}", "[]"))
    def test_no_usable_sources_stops_without_changing_repositories(self, arguments, content) -> None:
        registry = load_json(self.repos_path)
        registry["providers"] = [] if content == "[]" else {}
        save_json(self.repos_path, registry)
        snapshot = self.repos_path.read_bytes()
        self.open_url.side_effect = httpx2.ConnectError("offline")
        with (
            patch.object(audit_readme, "audit_repos_and_links") as audit,
            patch.object(find_projects, "run") as search,
        ):
            if content == "[]":
                with pytest.raises(ValidationError):
                    discover.main(arguments)
            else:
                assert discover.main(arguments) == 1
        assert self.repos_path.read_bytes() == snapshot
        audit.assert_not_called()
        search.assert_not_called()

    def test_main_preserves_custom_exclusions_and_existing_repo_state(self) -> None:
        save_json(
            self.custom_path,
            {"https://github.com/owner/disabled": {"enabled": False}},
        )
        discovery_state = load_json(self.repos_path)
        discovery_state["renames"] = {"https://github.com/owner/old": "https://github.com/owner/saved"}
        save_json(self.repos_path, discovery_state)
        data = {
            "bundles": [
                {"source": "github", "repo": "owner/disabled"},
                {"source": "github", "repo": "OWNER/SAVED"},
                {"source": "github", "repo": "owner/new"},
                {"source": "github", "repo": "owner/old"},
                {"source": "github", "repo": "owner/Old"},
            ]
        }
        with (
            patch.object(official, "request", return_value=httpx2.Response(200, json=data)),
            patch.object(
                jman,
                "request",
                return_value=httpx2.Response(200, json={"saved": {"patches": "https://github.com/owner/saved"}}),
            ),
            patch.object(
                morphe_archive,
                "request",
                return_value=httpx2.Response(200, text="https://morphe.software/add-source?github=owner/saved"),
            ),
        ):
            assert discover.main([]) == 0
        assert load_json(self.repos_path)["repositories"] == {
            **self.saved_repos,
            "https://github.com/owner/disabled": {"enabled": False},
            "https://github.com/owner/new": {},
        }
        assert load_json(self.repos_path)["renames"] == discovery_state["renames"]

    def test_snapshot_and_provider_write_failures_propagate(self) -> None:
        snapshot = self.official_path.read_bytes()
        sources = self.repos_path.read_bytes()
        with (
            patch.object(
                official,
                "request",
                return_value=httpx2.Response(200, json={"bundles": [{"source": "github", "repo": "owner/new"}]}),
            ),
            patch.object(official, "save_json", side_effect=OSError("disk full")),
            pytest.raises(OSError, match="disk full"),
        ):
            official.discover()
        assert self.official_path.read_bytes() == snapshot
        assert self.repos_path.read_bytes() == sources
        with (
            patch.object(self.open_url, "side_effect", httpx2.ConnectError("offline")),
            patch.object(discover, "save_json", side_effect=OSError("disk full")),
            pytest.raises(OSError, match="disk full"),
        ):
            discover.main([])

    def test_unexpected_provider_errors_stop_discovery_without_rewriting_repos(
        self,
    ) -> None:
        snapshot = self.repos_path.read_bytes()
        with (
            patch.object(official, "request", side_effect=RuntimeError("Unexpected failure")),
            patch.object(jman, "request", return_value=httpx2.Response(200, json={})),
            patch.object(morphe_archive, "request", return_value=httpx2.Response(200, text="")),
            pytest.raises(RuntimeError, match="Unexpected failure"),
        ):
            discover.main([])
        assert self.repos_path.read_bytes() == snapshot

    def test_default_does_not_audit_or_search_projects(self) -> None:
        self.open_url.side_effect = httpx2.ConnectError("offline")
        with (
            patch.object(audit_readme, "audit_repos_and_links") as audit,
            patch.object(find_projects, "run") as search,
        ):
            assert discover.main([]) == 0
        audit.assert_not_called()
        search.assert_not_called()

    def test_extended_discovery_exports_only_verified_unknown_projects(self) -> None:
        output_path = self.root / "projects.json"
        projects = {
            "readmeRepos": ["https://github.com/owner/archived", "https://github.com/owner/known-project"],
            "readmeLinks": [],
            "newRepos": [],
            "excludedRepos": ["https://github.com/owner/excluded-project"],
        }
        save_json(output_path, projects)
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

        def file_exists(url: str) -> bool:
            return url.endswith(
                (
                    "owner/new-project/develop/README.md",
                    "owner/patch-bundle/main/patches-bundle.json",
                )
            )

        with (
            patch.object(audit_readme, "PROJECTS_JSON_PATH", output_path),
            patch.object(audit_readme, "fetch_repo_details", return_value={"is_archived": True}),
            patch.multiple(
                find_projects,
                ROOT_DIR=self.root,
                PROJECTS_JSON_PATH=output_path,
                SEARCH_KEYWORDS=["morphe"],
                TARGET_USERS=[],
            ),
            patch.object(
                find_projects,
                "request",
                return_value=httpx2.Response(
                    200,
                    json={
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
                ),
            ) as search,
            patch.object(find_projects, "_file_exists", side_effect=file_exists),
        ):
            self.open_url.side_effect = httpx2.ConnectError("offline")
            assert discover.main(["--daily"]) == 0
            search.assert_called_once()
            summary = self.summary.call_args.args[0]
            assert "https://github.com/owner/archived" in summary
            assert load_json(output_path) == {**projects, "newRepos": [repository["html_url"]]}
            assert load_json(self.repos_path)["repositories"] == self.saved_repos


@pytest.mark.parametrize("reverse_custom", (False, True))
@pytest.mark.parametrize("renamed", (False, True))
def test_merge_keeps_provider_priority_and_later_custom_entries(
    reverse_custom,
    renamed,
) -> None:
    first_url = "https://github.com/Owner/Original" if renamed else "https://github.com/Owner/Repo"
    second_url = "https://github.com/owner/previous" if renamed else "https://github.com/owner/repo"
    custom_items = [
        (
            first_url,
            {"enabled": False, "note": "Earlier custom", "request": "Earlier request"},
        ),
        (
            second_url,
            {"enabled": True, "note": "Later custom", "extra": 7},
        ),
    ]
    renames: dict[str, str] = {}
    if renamed:
        destination = "https://github.com/Owner/Latest"
        renames = {first_url.lower(): destination, second_url.lower(): destination}
        custom_items.append((destination, {"enabled": True, "note": "Latest custom"}))
    if reverse_custom:
        custom_items.reverse()
    if not renamed:
        destination = custom_items[-1][0]
    providers = [
        dict(custom_items),
        {
            first_url.upper(): {
                "enabled": True,
                "note": "Official",
                "officialField": True,
            }
        },
        {first_url: {"note": "Archive", "archiveField": True}},
        {second_url: {"note": "Jman", "archiveField": False}},
    ]
    merged = discover.merge_sources(providers, renames)
    assert merged == {
        destination: {
            "enabled": not reverse_custom,
            "note": "Earlier custom" if reverse_custom else "Latest custom" if renamed else "Later custom",
            "request": "Earlier request",
            "extra": 7,
            "officialField": True,
            "archiveField": True,
        }
    }
    assert discover._sync_repos(merged, {}) == {destination: {"enabled": False} if reverse_custom else {}}


def test_sync_keeps_hosts_independent_and_preserves_saved_fields() -> None:
    github = "https://github.com/owner/repo"
    gitlab = "https://gitlab.com/owner/repo"
    saved = {github: {"main": "sha", "stars": 2, "renamedTo": "https://github.com/owner/new"}}
    actual = discover._sync_repos({github.upper(): {}, gitlab: {}}, saved)
    assert actual[github] == saved[github]
    assert actual[gitlab] == {}
    assert len(actual) == 2
    saved[github]["enabled"] = False
    assert discover._sync_repos({github: {}, gitlab: {}}, saved)[github] == actual[github]
