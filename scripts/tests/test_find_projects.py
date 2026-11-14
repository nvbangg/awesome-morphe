from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

from discovery import find_projects


@pytest.mark.parametrize(
    "metadata_status", (200, 404, 410, 403, 451, 429, 503, "network")
)
@pytest.mark.parametrize("readme_available", (False, True))
def test_candidate_checks_main_metadata_and_default_branch_readme(
    metadata_status, readme_available, block_network, patch_context
) -> None:
    metadata_url = (
        "https://raw.githubusercontent.com/owner/project/main/patches-bundle.json"
    )
    readme_url = "https://raw.githubusercontent.com/owner/project/develop/README.md"
    calls = []
    response = block_network.return_value
    response.__enter__.return_value.geturl.return_value = (
        "https://raw.githubusercontent.com/owner/renamed/develop/README.md"
    )

    def open_url(request, timeout):
        assert request.get_method() == "HEAD"
        assert timeout == find_projects.HEAD_TIMEOUT
        calls.append(request.full_url)
        status = (
            metadata_status
            if request.full_url == metadata_url
            else 200
            if readme_available
            else 404
        )
        if status == "network":
            raise URLError("DNS lookup failed")
        if status != 200:
            error = HTTPError(request.full_url, status, "Failed", Message(), None)
            patch_context.callback(error.close)
            raise error
        return response

    block_network.side_effect = open_url
    result = find_projects.is_valid_candidate(
        {"full_name": "owner/project", "default_branch": "develop"}
    )
    assert result == (metadata_status in (404, 410) and readme_available)
    assert calls == (
        [metadata_url, readme_url] if metadata_status in (404, 410) else [metadata_url]
    )
    response.__enter__.return_value.read.assert_not_called()


def test_candidate_readme_failure_does_not_become_a_project(
    block_network, patch_context
) -> None:
    missing = HTTPError("https://example.com/metadata", 404, "Missing", Message(), None)
    patch_context.callback(missing.close)
    block_network.side_effect = [missing, URLError("timed out")]
    assert not find_projects.is_valid_candidate({"full_name": "owner/project"})


@pytest.mark.parametrize("result_count", (1, 10))
def test_verified_projects_use_a_nested_list_and_collapsed_queries(
    tmp_path: Path, result_count
) -> None:
    candidates = [
        {
            "full_name": f"owner/project-{index}",
            "html_url": f"https://github.com/owner/project-{index}",
            "stargazers_count": index,
            "created_at": "2026-02-10T00:00:00Z",
            "pushed_at": "2026-11-13T00:00:00Z",
            "description": "Project description" if index == 0 else "",
        }
        for index in range(result_count + 1)
    ]
    output_path = tmp_path / "new-projects.txt"
    with (
        patch.multiple(
            find_projects,
            ROOT_DIR=tmp_path,
            PROJECTS_DIR=tmp_path,
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
    assert summary.startswith(
        f"<details>\n<summary><h3>New projects ({result_count})</h3></summary>\n\n"
    )
    assert summary.count("<details>") == summary.count("</details>") == 2
    assert "<summary>Search queries</summary>" in summary
    assert summary.count("- [owner/project-") == result_count
    assert "#### [" not in summary
    assert "**" not in summary
    assert "  - Created: `2026-02-10` | Updated: `2026-11-13`" in summary
    assert summary.count("  - Description: Project description") == 1
    assert "- [owner/project-0](https://github.com/owner/project-0) | ⭐ 0" in summary
    assert "New Repositories Found" not in summary
    assert len(output_path.read_text().strip().splitlines()) == result_count


def test_no_candidates_preserves_saved_project_file_and_reports_result(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "new-projects.txt"
    output_path.write_text("https://github.com/owner/saved-project\n", encoding="utf-8")
    with patch.object(find_projects, "NEW_PROJECTS_PATH", output_path):
        report = find_projects.verify_and_export_repos([])
    assert "<summary><h3>New projects (0)</h3></summary>" in report
    assert "No new standalone repositories found" in report
    assert "<summary>Search queries</summary>" in report
    assert "morphe size:>0" in report
    assert (
        output_path.read_text(encoding="utf-8")
        == "https://github.com/owner/saved-project\n"
    )
