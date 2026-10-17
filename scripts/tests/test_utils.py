import unittest
import urllib.error
from unittest.mock import patch

import utils


class FetchHelperTests(unittest.TestCase):
    def test_connection_error_is_not_retried(self) -> None:
        with (
            patch.object(
                utils.urllib.request,
                "urlopen",
                side_effect=urllib.error.URLError("DNS failed"),
            ) as open_url,
            self.assertRaises(urllib.error.URLError),
        ):
            utils.fetch("https://example.com/data")
        open_url.assert_called_once()

    def test_http_error_is_not_retried(self) -> None:
        error = urllib.error.HTTPError(
            "https://example.com/data", 503, "Unavailable", None, None
        )
        self.addCleanup(error.close)
        with (
            patch.object(
                utils.urllib.request, "urlopen", side_effect=error
            ) as open_url,
            self.assertRaises(urllib.error.HTTPError),
        ):
            utils.fetch("https://example.com/data")
        open_url.assert_called_once()

    def test_invalid_json_is_not_retried_or_reported_as_network_error(self) -> None:
        with patch.object(utils.urllib.request, "urlopen") as open_url:
            open_url.return_value.__enter__.return_value.read.return_value = b"{broken"
            with self.assertRaises(ValueError):
                utils.fetch("https://example.com/data", as_json=True)
        open_url.assert_called_once()


if __name__ == "__main__":
    unittest.main()
