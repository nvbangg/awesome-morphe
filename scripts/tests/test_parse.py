import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

import fetch as bundle_fetch
from common.utils import load_lines, save_json


class TestBundleParser:
    @pytest.fixture(autouse=True)
    def prepare(self, tmp_path: Path, patch_context) -> None:
        self.patch_context = patch_context
        self.root = tmp_path
        self.patches_dir = self.root / "patches"
        self.patches_dir.mkdir()
        self.updated_path = self.root / "updated_files.txt"
        self.parsed_path = self.root / "parsed_files.txt"
        self.gradle_path = self.root / bundle_fetch.GRADLE_EXECUTABLE_NAME
        self.patch_context.enter_context(
            patch.multiple(
                bundle_fetch,
                BUNDLE_PARSER_DIR=self.root,
                PATCHES_DIR=self.patches_dir,
                UPDATED_FILES_PATH=self.updated_path,
                PARSED_FILES_PATH=self.parsed_path,
                GRADLE_EXECUTABLE_PATH=self.gradle_path,
            )
        )
        self.run_process = self.patch_context.enter_context(
            patch.object(bundle_fetch.subprocess, "run")
        )

    def target(
        self, repo: str = "owner/alpha", branch: str = "main", source: str = "github"
    ) -> bundle_fetch.BranchFetchResult:
        return bundle_fetch.BranchFetchResult(
            source,
            repo,
            branch,
            "new-sha",
            status_changed=True,
            needs_parse=True,
            bundle_name=f"{repo} {branch}",
        )

    def complete_parser(
        self,
        targets: list[bundle_fetch.BranchFetchResult],
        content: str = '{"patches": [{"name": "Valid patch"}]}',
    ) -> None:

        def run_parser(
            *_args: object, **_kwargs: object
        ) -> subprocess.CompletedProcess:
            assert not self.parsed_path.exists()
            for target in targets:
                (self.patches_dir / f"{target.target_name}.json").write_text(
                    content, encoding="utf-8"
                )
            self.parsed_path.write_text(
                "\n".join(f"{target.target_name}.json" for target in targets),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess([], 0)

        self.run_process.side_effect = run_parser

    def test_empty_queue_does_not_launch_java_or_keep_old_queue(self) -> None:
        self.updated_path.write_text("mpp/stale.mpp", encoding="utf-8")
        bundle_fetch.run_bundle_parser([])
        self.run_process.assert_not_called()
        assert not self.updated_path.exists()

    def test_multiple_targets_use_one_batch_and_current_success_report(self) -> None:
        targets = [
            self.target(),
            self.target(branch="dev"),
            self.target("owner/beta", source="gitlab"),
        ]
        self.parsed_path.write_text("stale.json", encoding="utf-8")
        self.complete_parser(targets)
        bundle_fetch.run_bundle_parser(targets)
        self.run_process.assert_called_once_with(
            [str(self.gradle_path), "run", "--args=updated_files.txt"],
            cwd=str(self.root),
            text=True,
            check=True,
        )
        assert load_lines(self.updated_path) == [
            f"mpp/{target.target_name}.mpp" for target in targets
        ]
        assert all(target.new_sha == "new-sha" for target in targets)

    def test_process_failure_rejects_stale_success(self) -> None:
        target = self.target()
        self.parsed_path.write_text(f"{target.target_name}.json", encoding="utf-8")
        self.run_process.side_effect = subprocess.CalledProcessError(1, [])
        with pytest.raises(subprocess.CalledProcessError):
            bundle_fetch.run_bundle_parser([target])
        assert not self.parsed_path.exists()

    def test_launch_error_stops_processing(self) -> None:
        self.run_process.side_effect = OSError("Cannot start parser")
        with pytest.raises(OSError):
            bundle_fetch.run_bundle_parser([self.target()])

    def test_missing_success_report_stops_processing(self) -> None:
        self.run_process.return_value = subprocess.CompletedProcess([], 0)
        with pytest.raises(RuntimeError, match="did not write"):
            bundle_fetch.run_bundle_parser([self.target()])

    def test_partial_success_clears_only_failed_target_and_its_name(self) -> None:
        main_target = self.target()
        dev_target = self.target(branch="dev")
        save_json(
            self.patches_dir / f"{dev_target.target_name}.json",
            {"patches": [{"name": "Stale patch"}]},
        )
        self.complete_parser([main_target])
        bundle_fetch.run_bundle_parser([main_target, dev_target])
        assert main_target.new_sha == "new-sha"
        assert main_target.bundle_name == "owner/alpha main"
        assert dev_target.new_sha is None
        assert dev_target.bundle_name is None
        assert dev_target.error_message

    def test_success_entry_without_output_clears_target(self) -> None:
        target = self.target()

        def run_parser(
            *_args: object, **_kwargs: object
        ) -> subprocess.CompletedProcess:
            self.parsed_path.write_text(f"{target.target_name}.json", encoding="utf-8")
            return subprocess.CompletedProcess([], 0)

        self.run_process.side_effect = run_parser
        bundle_fetch.run_bundle_parser([target])
        assert target.new_sha is None

    @pytest.mark.parametrize("content", ("{broken", "{}", '{"patches": []}'))
    def test_output_content_validation_is_left_to_update(self, content) -> None:
        target = self.target()
        self.complete_parser([target], content=content)
        bundle_fetch.run_bundle_parser([target])
        assert target.new_sha == "new-sha"
        assert (self.patches_dir / f"{target.target_name}.json").read_text(
            encoding="utf-8"
        ) == content

    def test_failed_target_can_be_parsed_in_a_later_run(self) -> None:
        target = self.target()
        self.complete_parser([])
        bundle_fetch.run_bundle_parser([target])
        assert target.new_sha is None
        target = self.target()
        self.complete_parser([target])
        bundle_fetch.run_bundle_parser([target])
        assert target.new_sha == "new-sha"
