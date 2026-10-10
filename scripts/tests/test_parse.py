import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import parse as bundle_parse
from utils import load_json, load_lines, save_json


class BundleParserTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.root = Path(temporary_directory.name)
        self.parser_dir = self.root / "bundle-parser"
        self.mpp_dir = self.parser_dir / "mpp"
        self.patches_dir = self.root / "patches"
        self.mpp_dir.mkdir(parents=True)
        self.patches_dir.mkdir()
        self.repos_path = self.root / "repos.json"
        self.pending_path = self.parser_dir / "pending_repos.json"
        self.updated_path = self.parser_dir / "updated_files.txt"
        self.parsed_path = self.parser_dir / "parsed_files.txt"
        self.gradle_path = self.parser_dir / bundle_parse.GRADLE_EXECUTABLE_NAME
        self.gradle_path.touch()
        self.initial_repos = {
            "owner/alpha": {
                "name": "Alpha old",
                "github": {
                    "main": "alpha-old",
                    "dev": "alpha-dev-old",
                    "image": "image-old",
                },
            },
            "owner/beta": {
                "name": "Beta old",
                "github": {"main": "beta-old", "dev": None},
            },
        }
        save_json(self.repos_path, self.initial_repos)
        path_patcher = patch.multiple(
            bundle_parse,
            BUNDLE_PARSER_DIR=self.parser_dir,
            MPP_DIR=self.mpp_dir,
            PATCHES_DIR=self.patches_dir,
            REPOS_JSON_PATH=self.repos_path,
            PENDING_REPOS_PATH=self.pending_path,
            UPDATED_FILES_PATH=self.updated_path,
            PARSED_FILES_PATH=self.parsed_path,
            GRADLE_EXECUTABLE_PATH=self.gradle_path,
        )
        path_patcher.start()
        self.addCleanup(path_patcher.stop)
        process_patcher = patch.object(bundle_parse.subprocess, "run")
        self.run_process = process_patcher.start()
        self.addCleanup(process_patcher.stop)

    def queue_target(
        self, repo: str, name: str, branch: str = "main", source: str = "github"
    ) -> str:
        target_name = f"{source}~{repo.replace('/', '~')}~{branch}"
        updated_files = load_lines(self.updated_path)
        updated_files.append(f"mpp/{target_name}.mpp")
        self.updated_path.write_text("\n".join(updated_files), encoding="utf-8")
        self.write_manifest(target_name, name)
        return target_name

    def write_manifest(self, target_name: str, name: str) -> None:
        with zipfile.ZipFile(self.mpp_dir / f"{target_name}.mpp", "w") as mpp_file:
            mpp_file.writestr("META-INF/MANIFEST.MF", f"Name: {name}\n")

    def complete_parser(
        self, targets: list[str], returncode: int = bundle_parse.EXIT_SUCCESS
    ) -> None:
        def run_parser(
            *_args: object, **_kwargs: object
        ) -> subprocess.CompletedProcess:
            self.assertFalse(self.parsed_path.exists())
            for target_name in targets:
                save_json(
                    self.patches_dir / f"{target_name}.json",
                    {"patches": [{"name": "Valid patch"}]},
                )
            self.parsed_path.write_text(
                "\n".join(f"{target_name}.json" for target_name in targets),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess([], returncode)

        self.run_process.side_effect = run_parser

    def test_process_failure_rejects_stale_success_and_returns_failure(self) -> None:
        target_name = self.queue_target("owner/alpha", "Alpha new")
        self.parsed_path.write_text(f"{target_name}.json", encoding="utf-8")
        save_json(
            self.pending_path,
            {"owner/alpha": {"name": "Alpha new", "github": {"main": "alpha-new"}}},
        )
        self.run_process.return_value = subprocess.CompletedProcess(
            [], bundle_parse.EXIT_FAILURE
        )

        self.assertEqual(bundle_parse.main(), bundle_parse.EXIT_FAILURE)

        self.assertFalse(self.parsed_path.exists())
        self.assertEqual(load_json(self.repos_path), self.initial_repos)

    def test_process_failure_rejects_even_new_success_entries(self) -> None:
        target_name = self.queue_target("owner/alpha", "Alpha new")
        save_json(
            self.pending_path,
            {"owner/alpha": {"name": "Alpha new", "github": {"main": "alpha-new"}}},
        )
        self.complete_parser([target_name], returncode=bundle_parse.EXIT_FAILURE)

        self.assertFalse(bundle_parse.run_bundle_parser())

        self.assertEqual(load_json(self.repos_path), self.initial_repos)

    def test_launch_error_preserves_queued_target(self) -> None:
        self.queue_target("owner/alpha", "Alpha new")
        save_json(
            self.pending_path,
            {"owner/alpha": {"name": "Alpha new", "github": {"main": "alpha-new"}}},
        )
        self.run_process.side_effect = OSError("Cannot start parser")

        self.assertFalse(bundle_parse.run_bundle_parser())

        self.assertEqual(load_json(self.repos_path), self.initial_repos)

    def test_missing_success_file_is_process_failure(self) -> None:
        self.queue_target("owner/alpha", "Alpha new")
        self.run_process.return_value = subprocess.CompletedProcess(
            [], bundle_parse.EXIT_SUCCESS
        )

        self.assertEqual(bundle_parse.main(), bundle_parse.EXIT_FAILURE)

        self.assertEqual(load_json(self.repos_path), self.initial_repos)

    def test_partial_success_uses_name_of_accepted_branch(self) -> None:
        main_target = self.queue_target("owner/alpha", "Alpha main")
        self.queue_target("owner/alpha", "Alpha failed dev", branch="dev")
        save_json(
            self.pending_path,
            {
                "owner/alpha": {
                    "name": "Alpha failed dev",
                    "github": {"main": "alpha-new", "dev": "alpha-dev-new"},
                }
            },
        )
        self.complete_parser([main_target])

        self.assertEqual(bundle_parse.main(), bundle_parse.EXIT_SUCCESS)

        updated_repo = load_json(self.repos_path)["owner/alpha"]
        self.assertEqual(updated_repo["github"]["main"], "alpha-new")
        self.assertEqual(updated_repo["github"]["dev"], "alpha-dev-old")
        self.assertEqual(updated_repo["name"], "Alpha main")

    def test_failed_repo_name_does_not_leak_when_other_repo_succeeds(self) -> None:
        self.queue_target("owner/alpha", "Alpha failed")
        beta_target = self.queue_target("owner/beta", "Beta new")
        save_json(
            self.pending_path,
            {
                "owner/alpha": {
                    "name": "Alpha failed",
                    "github": {"main": "alpha-new"},
                },
                "owner/beta": {"name": "Beta new", "github": {"main": "beta-new"}},
            },
        )
        self.complete_parser([beta_target])

        self.assertTrue(bundle_parse.run_bundle_parser())

        updated_repos = load_json(self.repos_path)
        self.assertEqual(
            updated_repos["owner/alpha"], self.initial_repos["owner/alpha"]
        )
        self.assertEqual(updated_repos["owner/beta"]["name"], "Beta new")

    def test_invalid_output_is_not_accepted(self) -> None:
        target_name = self.queue_target("owner/alpha", "Alpha new")
        save_json(
            self.pending_path,
            {"owner/alpha": {"name": "Alpha new", "github": {"main": "alpha-new"}}},
        )
        output_path = self.patches_dir / f"{target_name}.json"
        for output in (None, "{broken", "{}", '{"patches": []}'):
            with self.subTest(output=output):

                def run_parser(
                    *_args: object, output: str | None = output, **_kwargs: object
                ) -> subprocess.CompletedProcess:
                    self.assertFalse(self.parsed_path.exists())
                    self.parsed_path.write_text(f"{target_name}.json", encoding="utf-8")
                    output_path.unlink(missing_ok=True)
                    if output is not None:
                        output_path.write_text(output, encoding="utf-8")
                    return subprocess.CompletedProcess([], bundle_parse.EXIT_SUCCESS)

                self.run_process.side_effect = run_parser

                self.assertTrue(bundle_parse.run_bundle_parser())

                self.assertEqual(load_json(self.repos_path), self.initial_repos)

    def test_failed_target_can_succeed_on_retry(self) -> None:
        target_name = self.queue_target("owner/alpha", "Alpha new")
        save_json(
            self.pending_path,
            {"owner/alpha": {"name": "Alpha new", "github": {"main": "alpha-new"}}},
        )
        self.complete_parser([])
        self.assertTrue(bundle_parse.run_bundle_parser())
        self.assertEqual(load_json(self.repos_path), self.initial_repos)

        self.complete_parser([target_name])
        self.assertTrue(bundle_parse.run_bundle_parser())

        self.assertEqual(
            load_json(self.repos_path)["owner/alpha"]["github"]["main"], "alpha-new"
        )

    def test_direct_patch_list_and_image_apply_without_java(self) -> None:
        target_name = "github~owner~alpha~main"
        self.write_manifest(target_name, "Alpha direct")
        save_json(
            self.pending_path,
            {
                "owner/alpha": {
                    "name": "Alpha direct",
                    "github": {"main": "alpha-direct", "image": "image-new"},
                }
            },
        )

        self.assertTrue(bundle_parse.run_bundle_parser())

        self.run_process.assert_not_called()
        updated_repo = load_json(self.repos_path)["owner/alpha"]
        self.assertEqual(updated_repo["github"]["main"], "alpha-direct")
        self.assertEqual(updated_repo["github"]["image"], "image-new")
        self.assertEqual(updated_repo["name"], "Alpha direct")

    def test_image_update_does_not_accept_failed_branch_name(self) -> None:
        self.queue_target("owner/alpha", "Alpha failed")
        save_json(
            self.pending_path,
            {
                "owner/alpha": {
                    "name": "Alpha failed",
                    "github": {"main": "alpha-new", "image": "image-new"},
                }
            },
        )
        self.run_process.return_value = subprocess.CompletedProcess(
            [], bundle_parse.EXIT_FAILURE
        )

        self.assertFalse(bundle_parse.run_bundle_parser())

        updated_repo = load_json(self.repos_path)["owner/alpha"]
        self.assertEqual(updated_repo["github"]["image"], "image-new")
        self.assertEqual(updated_repo["github"]["main"], "alpha-old")
        self.assertEqual(updated_repo["name"], "Alpha old")

    def test_unavailable_branch_does_not_reuse_old_manifest_name(self) -> None:
        self.write_manifest("github~owner~alpha~main", "Old manifest name")
        save_json(
            self.pending_path,
            {"owner/alpha": {"name": "Pending name", "github": {"main": None}}},
        )

        self.assertTrue(bundle_parse.run_bundle_parser())

        updated_repo = load_json(self.repos_path)["owner/alpha"]
        self.assertIsNone(updated_repo["github"]["main"])
        self.assertEqual(updated_repo["name"], "Alpha old")

    def test_no_pending_leaves_repos_unchanged(self) -> None:
        original_content = self.repos_path.read_bytes()
        save_json(self.pending_path, {})

        self.assertTrue(bundle_parse.run_bundle_parser())

        self.run_process.assert_not_called()
        self.assertEqual(self.repos_path.read_bytes(), original_content)


if __name__ == "__main__":
    unittest.main()
