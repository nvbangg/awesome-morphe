from unittest.mock import patch

import pytest

from common import repositories
from discovery import audit_readme


@pytest.mark.parametrize("source,code", (("github", 404), ("gitlab", 451)))
def test_audit_reports_unavailable_repositories(
    source, code, block_network, http_error
) -> None:
    repo_url = f"https://{source}.com/owner/alpha"
    error = http_error(repo_url, code)
    with (
        patch.object(repositories, "request", side_effect=error),
        patch.object(audit_readme, "load_lines", side_effect=[[repo_url], []]),
    ):
        block_network.side_effect = error
        report = audit_readme.audit_repos_and_links()
    assert repo_url in report
    assert str(code) in report


def test_audit_continues_after_one_repository_fails() -> None:
    failed_url = "https://gitlab.com/owner/failed"
    archived_url = "https://github.com/owner/archived"
    with (
        patch.object(
            audit_readme, "load_lines", side_effect=[[failed_url, archived_url], []]
        ),
        patch.object(
            audit_readme,
            "fetch_repo_details",
            side_effect=lambda url: (
                {"error": "Invalid data"}
                if url == failed_url
                else {"is_archived": True}
            ),
        ),
    ):
        report = audit_readme.audit_repos_and_links()
    assert failed_url in report
    assert archived_url in report
