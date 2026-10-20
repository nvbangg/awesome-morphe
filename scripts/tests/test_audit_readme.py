from unittest.mock import patch
from urllib.error import HTTPError

import pytest

from common import repo_info
from discovery import audit_readme


@pytest.mark.parametrize("code", repo_info.UNAVAILABLE_HTTP_CODES)
def test_audit_still_classifies_unavailable_repositories(code) -> None:
    repo_url = "https://github.com/owner/alpha"
    with (
        HTTPError("https://example.com", code, "Failed", None, None) as error,
        patch.object(repo_info.time, "sleep"),
        patch.object(repo_info, "fetch", side_effect=error),
        patch.object(audit_readme, "load_lines", side_effect=[[repo_url], []]),
    ):
        summary = audit_readme.audit_repos_and_links()
        assert f"{repo_url}: {code}" in summary
        assert "Other Errors" not in summary
        assert "#### Unavailable (1)" in summary


@pytest.mark.parametrize("result_count", (9, 10))
def test_audit_groups_collapse_independently_at_ten_results(result_count) -> None:
    with (
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
        patch.object(audit_readme, "fetch_repo_details", return_value={"is_404": True}),
        patch.object(
            audit_readme, "check_link_status", return_value={"error": "Timeout"}
        ),
    ):
        summary = audit_readme.audit_repos_and_links()
    unavailable, other = summary.split("#### Other Errors (1)")
    assert f"#### Unavailable ({result_count})" in unavailable
    assert ("<details>" in unavailable) == (result_count >= 10)
    assert "<details>" not in other
