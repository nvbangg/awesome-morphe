import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fetch as bundle_fetch
from utils import load_lines, save_json


class BundleParserTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.root = Path(temporary_directory.name)
        self.patches_dir = self.root / "patches"
        self.patches_dir.mkdir()
        self.updated_path = self.root / "updated_files.txt"
        self.parsed_path = self.root / "parsed_files.txt"
        self.gradle_path = self.root / bundle_fetch.GRADLE_EXECUTABLE_NAME
        path_patcher = patch.multiple(
            bundle_fetch,
            BUNDLE_PARSER_DIR=self.root,
            PATCHES_DIR=self.patches_dir,
            UPDATED_FILES_PATH=self.updated_path,
            PARSED_FILES_PATH=self.parsed_path,
            GRADLE_EXECUTABLE_PATH=self.gradle_path,
        )
        path_patcher.start()
        self.addCleanup(path_patcher.stop)
        process_patcher = patch.object(bundle_fetch.subprocess, "run")
        self.run_process = process_patcher.start()
        self.addCleanup(process_patcher.stop)

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
            self.assertFalse(self.parsed_path.exists())
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
        self.assertFalse(self.updated_path.exists())

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
        self.assertEqual(
            load_lines(self.updated_path),
            [f"mpp/{target.target_name}.mpp" for target in targets],
        )
        self.assertTrue(all(target.new_sha == "new-sha" for target in targets))

    def test_process_failure_rejects_stale_success(self) -> None:
        target = self.target()
        self.parsed_path.write_text(f"{target.target_name}.json", encoding="utf-8")
        self.run_process.side_effect = subprocess.CalledProcessError(1, [])
        with self.assertRaises(subprocess.CalledProcessError):
            bundle_fetch.run_bundle_parser([target])
        self.assertFalse(self.parsed_path.exists())

    def test_launch_error_stops_processing(self) -> None:
        self.run_process.side_effect = OSError("Cannot start parser")
        with self.assertRaises(OSError):
            bundle_fetch.run_bundle_parser([self.target()])

    def test_missing_success_report_stops_processing(self) -> None:
        self.run_process.return_value = subprocess.CompletedProcess([], 0)
        with self.assertRaisesRegex(RuntimeError, "did not write"):
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
        self.assertEqual(main_target.new_sha, "new-sha")
        self.assertEqual(main_target.bundle_name, "owner/alpha main")
        self.assertIsNone(dev_target.new_sha)
        self.assertIsNone(dev_target.bundle_name)
        self.assertTrue(dev_target.error_message)

    def test_success_entry_without_output_clears_target(self) -> None:
        target = self.target()

        def run_parser(
            *_args: object, **_kwargs: object
        ) -> subprocess.CompletedProcess:
            self.parsed_path.write_text(f"{target.target_name}.json", encoding="utf-8")
            return subprocess.CompletedProcess([], 0)

        self.run_process.side_effect = run_parser
        bundle_fetch.run_bundle_parser([target])
        self.assertIsNone(target.new_sha)

    def test_output_content_validation_is_left_to_update(self) -> None:
        for content in ("{broken", "{}", '{"patches": []}'):
            with self.subTest(content=content):
                target = self.target()
                self.complete_parser([target], content=content)
                bundle_fetch.run_bundle_parser([target])
                self.assertEqual(target.new_sha, "new-sha")
                self.assertEqual(
                    (self.patches_dir / f"{target.target_name}.json").read_text(
                        encoding="utf-8"
                    ),
                    content,
                )

    def test_failed_target_can_be_parsed_in_a_later_run(self) -> None:
        target = self.target()
        self.complete_parser([])
        bundle_fetch.run_bundle_parser([target])
        self.assertIsNone(target.new_sha)
        target = self.target()
        self.complete_parser([target])
        bundle_fetch.run_bundle_parser([target])
        self.assertEqual(target.new_sha, "new-sha")


if __name__ == "__main__":
    unittest.main()
