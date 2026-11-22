import argparse
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

import audit_readme
import discover
import fetch
import find_projects
import telegram
import update
from common import http
from common.constants import ROOT_DIR, SCRIPTS_DIR, WHATS_NEW_PATH
from common.summary import append_step_summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sync Morphe bundles and projects. Without a command, run the normal sync pipeline.",
        epilog="Use uv run main.py COMMAND --help for command details.",
    )
    parser.add_argument("--daily", action="store_true", help="Enable daily refresh for sync, fetch or update")
    commands = parser.add_subparsers(dest="task", title="commands")
    commands.add_parser(
        "audit-readme",
        help="Check README repositories and links",
        description="Check README repositories and links",
    )
    commands.add_parser(
        "find-projects",
        help="Find new projects for manual review",
        description="Find new projects for manual review",
    )
    commands.add_parser("discover", help="Collect bundle sources", description="Collect bundle sources")
    fetch_parser = commands.add_parser(
        "fetch",
        help="Refresh repository metadata and fetch bundle data",
        description="Refresh repository metadata and fetch bundle data",
    )
    fetch_parser.add_argument(
        "--daily",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Also recheck bundle downloads and image hashes",
    )
    update_parser = commands.add_parser(
        "update", help="Build the catalog from local data", description="Build the catalog from local data"
    )
    update_parser.add_argument(
        "--daily",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Also refresh all app metadata and generate the changelog",
    )
    notification = commands.add_parser(
        "telegram",
        help="Send a Markdown notification to Telegram",
        description="Send a Markdown notification to Telegram.",
    )
    notification.add_argument(
        "title", nargs="?", metavar="TITLE", help="Notification title (default: generated from the UTC date)"
    )
    notification.add_argument(
        "filepath",
        nargs="?",
        type=Path,
        default=WHATS_NEW_PATH,
        metavar="FILEPATH",
        help=f"Markdown file (default: {WHATS_NEW_PATH.relative_to(ROOT_DIR).as_posix()})",
    )
    args = parser.parse_args(argv)
    daily = getattr(args, "daily", False)
    if args.task not in (None, "fetch", "update") and daily:
        parser.error(f"{args.task} does not accept --daily")

    load_dotenv(SCRIPTS_DIR / ".env", override=True)
    with http.HTTP_CLIENT:
        if args.task == "telegram":
            telegram.send_notification(args.title, args.filepath)
            return 0

        if args.task in ("audit-readme", "find-projects") or (args.task is None and daily):
            sections = ["## 📋 Review:"]
            if args.task in (None, "audit-readme"):
                sections.append(audit_readme.audit_repos_and_links())
            if args.task in (None, "find-projects"):
                sections.append(find_projects.run())
            append_step_summary("\n\n".join(sections))
            if args.task is not None:
                return 0

        if args.task in (None, "discover"):
            result = discover.run()
            if result or args.task == "discover":
                return result

        if args.task in (None, "fetch"):
            fetch.fetch_all_repos(daily)
            if args.task == "fetch":
                return 0

        if (
            args.task is None
            and not daily
            and not subprocess.check_output(
                ["git", "status", "--porcelain", "--", "data/", "web/public/"], cwd=ROOT_DIR
            )
        ):
            return 0

        result = update.run(daily)
        if result == 0 and (output_path := os.environ.get("GITHUB_OUTPUT")):
            with Path(output_path).open("a", encoding="utf-8") as file:
                file.write("updated=true\n")
        return result


if __name__ == "__main__":
    sys.exit(main())
