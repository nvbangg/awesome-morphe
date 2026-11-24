from pathlib import Path
from unittest.mock import patch

import httpx2
import pytest

import discover
from common.files import load_json, save_json
from discovery import jman, morphe_archive, official


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
        save_json(self.official_path, {"bundles": [], "store": {"saved": {}}})
        save_json(self.custom_path, {})
        save_json(
            self.repos_path,
            {
                "repositories": self.saved_sources,
                "providers": {name: list(self.saved_sources) for name in discover.PROVIDER_MODULES},
            },
        )
        for patcher in (
            patch.multiple(
                discover,
                CUSTOM_JSON_PATH=self.custom_path,
                DISCOVERY_JSON_PATH=self.repos_path,
            ),
            patch.object(official, "OFFICIAL_BUNDLES_PATH", self.official_path),
        ):
            self.patch_context.enter_context(patcher)
        self.patch_context.enter_context(patch.object(discover, "append_step_summary"))
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
            (jman, {"data": {"source": []}}),
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

    @pytest.mark.parametrize(
        "last_page",
        (
            {"data": {"source": [{"url": "https://gitlab.com/group/project"}]}},
            {"errors": [{"message": "Query failed"}], "data": {"source": []}},
            httpx2.ReadTimeout("timed out"),
        ),
    )
    def test_jman_pagination_is_complete_or_keeps_saved_sources(self, last_page) -> None:
        pages = [
            httpx2.Response(
                200,
                json={
                    "data": {
                        "source": [{"url": "https://github.com/owner/new"}, {"url": "https://example.com/unrelated"}]
                    }
                },
            ),
            last_page if isinstance(last_page, Exception) else httpx2.Response(200, json=last_page),
        ]
        with patch.object(jman, "PAGE_SIZE", 2), patch.object(jman, "request", side_effect=pages) as request:
            result, error = jman.discover()
        assert [call.kwargs["json"]["variables"] for call in request.call_args_list] == [
            {"limit": 2, "offset": 0},
            {"limit": 2, "offset": 2},
        ]
        if isinstance(last_page, Exception):
            assert (result, error) == ([], "timed out")
        elif "errors" in last_page:
            assert (result, error) == ([], "Invalid provider data")
        else:
            assert (result, error) == (["https://github.com/owner/new", "https://gitlab.com/group/project"], None)

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
            assert discover.run() == 0
            saved_repos = self.repos_path.read_bytes()
            request.return_value = httpx2.Response(200, text="\n".join(reversed(content.splitlines())))
            assert discover.run() == 0
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
        assert discover.run() == 0
        assert load_json(self.repos_path)["repositories"] == self.saved_sources

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
            discover.run()

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
            discover.run()
        assert self.repos_path.read_bytes() == snapshot

    def test_custom_config_is_filtered_and_later_case_variant_wins(self) -> None:
        save_json(
            self.custom_path,
            {
                "https://github.com/owner/saved": {"enabled": False, "note": "Private", "revancedStars": 5},
                "https://github.com/OWNER/SAVED": {"revancedStars": 8, "request": "Private"},
                "https://gitlab.com/owner/new": {"enabled": False},
                "https://github.com/aaa/custom": {},
            },
        )
        before = self.custom_path.read_bytes()
        registry = load_json(self.repos_path)
        registry["repositories"] = {
            "https://github.com/owner/saved": {"id": "github:1", "enabled": False, "revancedStars": 99},
            "https://github.com/aaa/custom": {
                "id": "github:2",
                "etag": 'W/"saved"',
                "enabled": False,
                "revancedStars": 20,
            },
            "https://github.com/owner/stale": {"id": "github:3", "etag": '"removed"'},
        }
        save_json(self.repos_path, registry)
        self.open_url.side_effect = httpx2.ConnectError("offline")
        assert discover.run() == 0
        repositories = load_json(self.repos_path)["repositories"]
        assert repositories == {
            "https://github.com/aaa/custom": {"id": "github:2", "etag": 'W/"saved"'},
            "https://github.com/owner/saved": {"revancedStars": 8, "id": "github:1"},
            "https://gitlab.com/owner/new": {"enabled": False},
        }
        assert list(repositories) == [
            "https://github.com/aaa/custom",
            "https://github.com/owner/saved",
            "https://gitlab.com/owner/new",
        ]
        assert self.custom_path.read_bytes() == before

    def test_empty_sources_stop_without_replacing_saved_discovery(self) -> None:
        save_json(self.repos_path, {"providers": {}, "repositories": {}})
        before = self.repos_path.read_bytes()
        self.open_url.side_effect = httpx2.ConnectError("offline")
        assert discover.run() == 1
        assert self.repos_path.read_bytes() == before
