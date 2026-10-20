import os
import shutil
import subprocess
import sys
import urllib.error
from email.message import Message
from pathlib import Path
from unittest.mock import patch

import pytest

from common import utils

DOTENV_TEST_VARIABLE = "MORPHE_DOTENV_TEST_VALUE"


class TestDotenvLoading:
    @pytest.fixture(autouse=True)
    def prepare(self, tmp_path: Path) -> None:
        self.root = tmp_path
        self.scripts_dir = self.root / "scripts"
        self.scripts_dir.mkdir()
        common_dir = self.scripts_dir / "common"
        common_dir.mkdir()
        self.utils_path = common_dir / "utils.py"
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
        assert self.import_utils() == "from-file"

    def test_existing_environment_variable_takes_priority(self) -> None:
        (self.scripts_dir / ".env").write_text(
            f"{DOTENV_TEST_VARIABLE}=from-file\n", encoding="utf-8"
        )
        assert self.import_utils("from-environment") == "from-environment"

    def test_missing_dotenv_keeps_existing_environment(self) -> None:
        assert self.import_utils("from-environment") == "from-environment"
        assert self.import_utils() == ""

    def test_shared_paths_still_resolve_from_the_repository_root(self) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        assert repository_root == utils.ROOT_DIR
        assert repository_root / "scripts" == utils.SCRIPTS_DIR
        assert repository_root / "data/repos.json" == utils.REPOS_JSON_PATH
        assert repository_root / "scripts/bundle-parser" == utils.BUNDLE_PARSER_DIR


def test_connection_error_is_not_retried() -> None:
    with (
        patch.object(
            utils.urllib.request,
            "urlopen",
            side_effect=urllib.error.URLError("DNS failed"),
        ) as open_url,
        pytest.raises(urllib.error.URLError),
    ):
        utils.fetch("https://example.com/data")
    open_url.assert_called_once()


def test_http_error_is_not_retried(patch_context) -> None:
    error = urllib.error.HTTPError(
        "https://example.com/data", 503, "Unavailable", Message(), None
    )
    patch_context.callback(error.close)
    with (
        patch.object(utils.urllib.request, "urlopen", side_effect=error) as open_url,
        pytest.raises(urllib.error.HTTPError),
    ):
        utils.fetch("https://example.com/data")
    open_url.assert_called_once()


def test_invalid_json_is_not_retried_or_reported_as_network_error() -> None:
    with patch.object(utils.urllib.request, "urlopen") as open_url:
        open_url.return_value.__enter__.return_value.read.return_value = b"{broken"
        with pytest.raises(ValueError):
            utils.fetch("https://example.com/data", as_json=True)
    open_url.assert_called_once()


@pytest.mark.parametrize("result_count", (0, 1, 9, 10, 11))
def test_result_count_controls_details_at_the_threshold(result_count) -> None:
    content = "\n".join(f"- Result {index}" for index in range(result_count))
    section = utils.format_summary_section("Results", content, result_count)
    assert section.startswith(f"### Results ({result_count})\n\n")
    assert content in section
    if result_count >= 10:
        assert section.count("<details>") == 1
        assert "<summary>Show details</summary>\n\n" in section
        assert section.endswith("\n\n</details>")
    else:
        assert "<details>" not in section


def test_details_use_result_count_instead_of_content_line_count() -> None:
    content = "\n".join(f"- Detail {index}" for index in range(20))
    section = utils.format_summary_section("Warnings", content, 1, heading_level=4)
    assert section == f"#### Warnings (1)\n\n{content}"


def test_sections_in_separate_step_files_have_one_separator_each(
    tmp_path: Path,
) -> None:
    root = tmp_path
    paths = []
    for section_name in ("Discover", "Fetch", "Update"):
        path = root / f"{section_name}.md"
        with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(path)}):
            utils.append_step_summary(f"## {section_name}:\n\n- Warning")
        paths.append(path)
        assert path.read_text(encoding="utf-8").endswith("\n\n---\n\n")
    summary = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert summary.count("\n---\n") == len(paths)


def test_empty_content_does_not_create_summary_or_separator(tmp_path: Path) -> None:
    path = tmp_path / "summary.md"
    with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(path)}):
        utils.append_step_summary(" \n ")
    assert not path.exists()
