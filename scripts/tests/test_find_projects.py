from pathlib import Path
from unittest.mock import patch

import httpx2
import pytest

import find_projects
from common.files import load_json, save_json


@pytest.mark.parametrize(
    "metadata_status,readme_status,expected",
    (
        (200, 200, False),
        (404, 200, True),
        (410, 200, True),
        (404, 404, False),
        (403, 200, False),
        (404, "network", False),
    ),
)
def test_project_requires_confirmed_missing_bundle_and_available_readme(
    metadata_status, readme_status, expected, block_network
) -> None:
    statuses = {
        "https://raw.githubusercontent.com/owner/project/main/patches-bundle.json": metadata_status,
        "https://raw.githubusercontent.com/owner/project/develop/README.md": readme_status,
    }

    def open_url(request):
        status = statuses[str(request.url)]
        if status == "network":
            raise httpx2.ConnectError("DNS lookup failed", request=request)
        return httpx2.Response(status)

    block_network.side_effect = open_url
    assert find_projects.is_valid_candidate({"full_name": "owner/project", "default_branch": "develop"}) == expected


def test_only_verified_projects_are_exported(tmp_path: Path) -> None:
    candidates = [
        {"full_name": "owner/valid", "html_url": "https://github.com/owner/valid"},
        {
            "full_name": "owner/rejected",
            "html_url": "https://github.com/owner/rejected",
        },
    ]
    output_path = tmp_path / "projects.json"
    saved = {
        "readmeRepos": ["https://github.com/owner/zebra", "https://github.com/owner/alpha"],
        "readmeLinks": ["https://example.com/second", "https://example.com/first"],
        "newRepos": ["https://github.com/owner/saved-project"],
        "excludedRepos": ["https://github.com/owner/last", "https://github.com/owner/first"],
    }
    save_json(output_path, saved)
    with (
        patch.multiple(
            find_projects,
            ROOT_DIR=tmp_path,
            PROJECTS_JSON_PATH=output_path,
        ),
        patch.object(
            find_projects,
            "is_valid_candidate",
            side_effect=lambda repo: repo["full_name"] == "owner/valid",
        ),
    ):
        report = find_projects.verify_and_export_repos(candidates)
        first_result = output_path.read_bytes()
        find_projects.verify_and_export_repos(candidates)
    assert load_json(output_path) == {**saved, "newRepos": ["https://github.com/owner/valid"]}
    assert output_path.read_bytes() == first_result
    assert "https://github.com/owner/valid" in report
    assert "https://github.com/owner/rejected" not in report


def test_no_candidates_preserves_saved_project_file(tmp_path: Path) -> None:
    output_path = tmp_path / "projects.json"
    save_json(
        output_path,
        {
            "readmeRepos": [],
            "readmeLinks": [],
            "newRepos": ["https://github.com/owner/saved-project"],
            "excludedRepos": [],
        },
    )
    saved_content = output_path.read_bytes()
    with patch.object(find_projects, "PROJECTS_JSON_PATH", output_path):
        find_projects.verify_and_export_repos([])
    assert output_path.read_bytes() == saved_content
