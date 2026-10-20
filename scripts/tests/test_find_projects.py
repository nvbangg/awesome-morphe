from pathlib import Path
from unittest.mock import patch

import pytest

from discovery import find_projects


@pytest.mark.parametrize("result_count", (9, 10))
def test_project_details_depend_on_verified_project_count(
    tmp_path: Path, result_count
) -> None:
    candidates = [
        {
            "full_name": f"owner/project-{index}",
            "html_url": f"https://github.com/owner/project-{index}",
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
    assert summary.startswith(f"### New projects ({result_count})\n\n")
    assert ("<details>" in summary) == (result_count >= 10)
    assert summary.count("#### [owner/project-") == result_count
    assert "New Repositories Found" not in summary
    assert len(output_path.read_text().splitlines()) == result_count


def test_no_candidates_preserves_saved_project_file_and_reports_result(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "new-projects.txt"
    output_path.write_text("https://github.com/owner/saved-project\n", encoding="utf-8")
    with patch.object(find_projects, "NEW_PROJECTS_PATH", output_path):
        report = find_projects.verify_and_export_repos([])
    assert "### New projects" in report
    assert "No new standalone repositories found" in report
    assert (
        output_path.read_text(encoding="utf-8")
        == "https://github.com/owner/saved-project\n"
    )
