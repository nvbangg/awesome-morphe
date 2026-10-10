# Copyright (c) 2026 nvbangg (github.com/nvbangg)

import subprocess
import sys
from pathlib import Path

from updater.local_parse import parse_patches_list
from utils import (
    BUNDLE_PARSER_DIR,
    DEFAULT_BRANCHES,
    MPP_DIR,
    PARSED_FILES_PATH,
    PATCHES_DIR,
    PENDING_REPOS_PATH,
    REPOS_JSON_PATH,
    UPDATED_FILES_PATH,
    extract_mpp_name,
    load_json,
    load_lines,
    save_json,
)

GRADLE_EXECUTABLE_NAME = "gradlew.bat" if sys.platform == "win32" else "gradlew"
GRADLE_EXECUTABLE_PATH = BUNDLE_PARSER_DIR / GRADLE_EXECUTABLE_NAME
EXIT_SUCCESS = 0
EXIT_FAILURE = 1


def commit_pending_repos(
    updated_files: list[str], successful_parsed_files: set[str]
) -> None:
    updated_targets = {Path(file_path).stem for file_path in updated_files}
    valid_parsed_targets = set()
    for target_name in sorted(updated_targets):
        parsed_file = f"{target_name}.json"
        if parsed_file not in successful_parsed_files:
            print(f"[-] Failed to parse bundle: {target_name}")
            continue
        try:
            patches, reason = parse_patches_list(
                load_json(PATCHES_DIR / parsed_file), {}
            )
        except Exception as error:
            patches, reason = None, str(error)
        if not patches:
            print(f"[-] Invalid parser output for {target_name}: {reason}")
            continue
        valid_parsed_targets.add(target_name)

    if not (pending_repos := load_json(PENDING_REPOS_PATH, {})):
        return

    repos_data = load_json(REPOS_JSON_PATH, {})
    committed_target_count = 0

    for repo, repo_updates in pending_repos.items():
        if "/" not in repo:
            continue

        for source in ("github", "gitlab"):
            if not isinstance(source_updates := repo_updates.get(source), dict):
                continue

            if "image" in source_updates:
                source_data = repos_data.setdefault(repo, {}).setdefault(source, {})
                source_data["image"] = source_updates["image"]
                committed_target_count += 1

            for branch in DEFAULT_BRANCHES:
                if branch in source_updates:
                    new_sha = source_updates[branch]
                    target_name = f"{source}~{repo.replace('/', '~')}~{branch}"
                    if (
                        target_name not in updated_targets
                        or target_name in valid_parsed_targets
                    ):
                        source_data = repos_data.setdefault(repo, {}).setdefault(
                            source, {}
                        )
                        source_data[branch] = new_sha
                        committed_target_count += 1
                        if (
                            new_sha is not None
                            and repo_updates.get("name")
                            and (
                                name := extract_mpp_name(MPP_DIR / f"{target_name}.mpp")
                            )
                        ):
                            repos_data[repo]["name"] = name

    if committed_target_count > 0:
        formatted_repos_data = {}
        for repo, entry in sorted(repos_data.items(), key=lambda item: item[0].lower()):
            if not isinstance(entry, dict):
                continue
            repo_entry = {}
            if "name" in entry:
                repo_entry["name"] = entry["name"]
            for source in ("github", "gitlab"):
                if source in entry and isinstance(entry[source], dict):
                    source_entry = {
                        "main": entry[source].get("main"),
                        "dev": entry[source].get("dev"),
                    }
                    if "image" in entry[source]:
                        source_entry["image"] = entry[source]["image"]
                    repo_entry[source] = source_entry
            formatted_repos_data[repo] = repo_entry
        save_json(REPOS_JSON_PATH, formatted_repos_data)
        print(
            f"Successfully committed pending SHA updates for {committed_target_count} target(s) to repos.json."
        )


def run_bundle_parser() -> bool:
    updated_files = load_lines(UPDATED_FILES_PATH)

    parse_error = None
    successful_parsed_files = set()
    if updated_files:
        print("\nRunning bundle-parser to extract patches-list from .mpp files...")
        command_args = [
            str(GRADLE_EXECUTABLE_PATH),
            "run",
            "--args=@updated_files.txt",
        ]
        try:
            PARSED_FILES_PATH.unlink(missing_ok=True)
            execution_result = subprocess.run(
                command_args, cwd=str(BUNDLE_PARSER_DIR), text=True
            )
            if execution_result.returncode != 0:
                parse_error = (
                    f"bundle-parser exited with code {execution_result.returncode}"
                )
            elif not PARSED_FILES_PATH.is_file():
                parse_error = "bundle-parser did not write parsed_files.txt"
            else:
                successful_parsed_files = set(load_lines(PARSED_FILES_PATH))
                print("bundle-parser completed successfully.")
        except Exception as error:
            parse_error = f"bundle-parser failed to execute: {error}"
    else:
        print("[-] No updated_files.txt found or empty. Nothing to parse.")

    if parse_error:
        print(f"[-] {parse_error}")
    commit_pending_repos(updated_files, successful_parsed_files)
    return parse_error is None


def main() -> int:
    return EXIT_SUCCESS if run_bundle_parser() else EXIT_FAILURE


if __name__ == "__main__":
    sys.exit(main())
