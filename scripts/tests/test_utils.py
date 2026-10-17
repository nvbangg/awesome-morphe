import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import utils

DOTENV_TEST_VARIABLE = "MORPHE_DOTENV_TEST_VALUE"


class DotenvLoadingTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.root = Path(temporary_directory.name)
        self.scripts_dir = self.root / "scripts"
        self.scripts_dir.mkdir()
        self.utils_path = self.scripts_dir / "utils.py"
        shutil.copyfile(utils.__file__, self.utils_path)

    def import_utils(self, existing_value: str | None = None) -> str:
        environment = dict(os.environ)
        environment.pop(DOTENV_TEST_VARIABLE, None)
        environment.pop("PYTHON_DOTENV_DISABLED", None)
        if existing_value is not None:
            environment[DOTENV_TEST_VARIABLE] = existing_value
        return subprocess.check_output(
            [
                sys.executable,
                "-B",
                "-c",
                "import os, runpy, sys; runpy.run_path(sys.argv[1]); print(os.environ.get(sys.argv[2], ''))",
                str(self.utils_path),
                DOTENV_TEST_VARIABLE,
            ],
            cwd=self.root,
            env=environment,
            text=True,
        ).strip()

    def test_loads_scripts_dotenv_from_another_working_directory(self) -> None:
        (self.scripts_dir / ".env").write_text(
            f"{DOTENV_TEST_VARIABLE}=from-file\n", encoding="utf-8"
        )
        self.assertEqual(self.import_utils(), "from-file")

    def test_existing_environment_variable_takes_priority(self) -> None:
        (self.scripts_dir / ".env").write_text(
            f"{DOTENV_TEST_VARIABLE}=from-file\n", encoding="utf-8"
        )
        self.assertEqual(self.import_utils("from-environment"), "from-environment")

    def test_missing_dotenv_keeps_existing_environment(self) -> None:
        self.assertEqual(self.import_utils("from-environment"), "from-environment")
        self.assertEqual(self.import_utils(), "")


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


class StepSummaryTests(unittest.TestCase):
    def test_sections_in_separate_step_files_have_one_separator_each(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            paths = []
            for section_name in ("Discover", "Fetch", "Update"):
                path = root / f"{section_name}.md"
                with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(path)}):
                    utils.append_step_summary(f"## {section_name}:\n\n- Warning")
                paths.append(path)
                self.assertTrue(
                    path.read_text(encoding="utf-8").endswith("\n\n---\n\n")
                )
            summary = "\n".join(path.read_text(encoding="utf-8") for path in paths)
            self.assertEqual(summary.count("\n---\n"), len(paths))

    def test_empty_content_does_not_create_summary_or_separator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "summary.md"
            with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(path)}):
                utils.append_step_summary(" \n ")
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
