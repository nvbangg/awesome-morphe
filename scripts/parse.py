# Copyright (c) 2026 nvbangg (github.com/nvbangg)

import stat
import subprocess
import sys
from pathlib import Path

from utils import (
    BUNDLE_PARSER_DIR,
    DEFAULT_BRANCHES,
    PARSED_FILES_PATH,
    PENDING_REPOS_PATH,
    REPOS_JSON_PATH,
    UPDATED_FILES_PATH,
    load_json,
    load_lines,
    save_json,
)

GRADLE_EXECUTABLE_NAME = "gradlew.bat" if sys.platform == "win32" else "gradlew"
GRADLE_EXECUTABLE_PATH = BUNDLE_PARSER_DIR / GRADLE_EXECUTABLE_NAME


def commit_pending_repos(
    updated_files: list[str] | None = None, parse_error: str | None = None
) -> None:
    updated_files_set = set(updated_files or [])
    successful_parsed_files = set(load_lines(PARSED_FILES_PATH))

    if parse_error:
        print(f"[-] {parse_error}")
    if updated_files:
        for file_path in sorted(updated_files):
            target_name = Path(file_path).stem
            if f"{target_name}.json" not in successful_parsed_files:
                print(f"[-] Failed to parse bundle: {target_name}")

    if not (pending_repos := load_json(PENDING_REPOS_PATH, {})):
        return

    repos_data = load_json(REPOS_JSON_PATH, {})
    committed_target_count = 0

    for repo, repo_updates in pending_repos.items():
        if "/" not in repo:
            continue

        if name := repo_updates.get("name"):
            repos_data.setdefault(repo, {})["name"] = name

        for source in ("github", "gitlab"):
            if not isinstance(source_updates := repo_updates.get(source), dict):
                continue

            source_data = repos_data.setdefault(repo, {}).setdefault(source, {})
            if "image" in source_updates:
                source_data["image"] = source_updates["image"]
                committed_target_count += 1

            for branch in DEFAULT_BRANCHES:
                if branch in source_updates:
                    new_sha = source_updates[branch]
                    file_prefix = f"{source}~{repo.replace('/', '~')}~{branch}"
                    is_mpp_target = f"mpp/{file_prefix}.mpp" in updated_files_set
                    parsed_file = f"{file_prefix}.json"
                    if not is_mpp_target or parsed_file in successful_parsed_files:
                        source_data[branch] = new_sha
                        committed_target_count += 1

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


def run_bundle_parser() -> None:
    updated_files = load_lines(UPDATED_FILES_PATH)

    parse_error = None
    if updated_files:
        print("\nRunning bundle-parser to extract patches-list from .mpp files...")
        if sys.platform != "win32" and GRADLE_EXECUTABLE_PATH.exists():
            GRADLE_EXECUTABLE_PATH.chmod(
                GRADLE_EXECUTABLE_PATH.stat().st_mode
                | stat.S_IXUSR
                | stat.S_IXGRP
                | stat.S_IXOTH
            )

        command_args = [
            str(GRADLE_EXECUTABLE_PATH),
            "run",
            "--args=@updated_files.txt",
        ]
        try:
            execution_result = subprocess.run(
                command_args, cwd=str(BUNDLE_PARSER_DIR), text=True
            )
            if execution_result.returncode != 0:
                parse_error = (
                    f"bundle-parser exited with code {execution_result.returncode}"
                )
                print(f"[-] {parse_error}")
            else:
                print("bundle-parser completed successfully.")
        except Exception as error:
            parse_error = f"bundle-parser failed to execute: {error}"
            print(f"[-] {parse_error}")
    else:
        print("[-] No updated_files.txt found or empty. Nothing to parse.")

    commit_pending_repos(updated_files, parse_error)


def main() -> None:
    run_bundle_parser()


if __name__ == "__main__":
    sys.exit(main())
