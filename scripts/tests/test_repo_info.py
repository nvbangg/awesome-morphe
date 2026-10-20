import urllib.error
from unittest.mock import patch

import pytest

from common import repo_info


class TestRepositoryMetadata:
    @pytest.fixture(autouse=True)
    def prepare(self, patch_context, block_network) -> None:
        self.patch_context = patch_context
        self.patch_context.enter_context(patch.object(repo_info.time, "sleep"))
        self.open_url = block_network

    def http_error(self, code: int) -> urllib.error.HTTPError:
        error = urllib.error.HTTPError(
            "https://example.com", code, "Failed", None, None
        )
        self.patch_context.callback(error.close)
        return error

    @pytest.mark.parametrize("code", (404, 451, 403, 503))
    def test_github_http_errors_keep_actual_status_and_audit_flags(self, code) -> None:
        with patch.object(repo_info, "fetch", side_effect=self.http_error(code)):
            details = repo_info.fetch_repo_details("https://github.com/owner/alpha")
            expected = {"error": f"Request failed (HTTP {code})"}
            if code in repo_info.UNAVAILABLE_HTTP_CODES:
                expected[f"is_{code}"] = True
            assert details == expected

    def test_connection_error_reports_reason_without_fabricating_http_status(
        self,
    ) -> None:
        with patch.object(
            repo_info, "fetch", side_effect=urllib.error.URLError("DNS lookup failed")
        ):
            details = repo_info.fetch_repo_details("https://github.com/owner/alpha")
        assert details == {"error": "Request failed: DNS lookup failed"}

    @pytest.mark.parametrize(
        "failure_kind,expected",
        (
            ("http", "Request failed (HTTP 503)"),
            ("network", "Request failed: timed out"),
        ),
    )
    def test_gitlab_request_errors_report_actual_status_or_exception_reason(
        self, failure_kind, expected
    ) -> None:
        error = (
            self.http_error(503)
            if failure_kind == "http"
            else urllib.error.URLError("timed out")
        )
        self.open_url.side_effect = error
        assert repo_info.fetch_gitlab_repo_details("owner/alpha") == {"error": expected}

    def test_missing_gitlab_project_does_not_claim_an_http_error(self) -> None:
        self.open_url.side_effect = None
        self.open_url.return_value.__enter__.return_value.read.return_value = (
            b'{"data": {"project": null}}'
        )
        assert repo_info.fetch_gitlab_repo_details("owner/alpha") == {
            "is_404": True,
            "error": "Repository not found or inaccessible",
        }
