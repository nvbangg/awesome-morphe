import argparse
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

import discover
import fetch
import telegram
import update
from common import http
from common.constants import ROOT_DIR, SCRIPTS_DIR, WHATS_NEW_PATH
from common.summary import append_step_summary
from discovery import audit_readme, find_projects


def main(argv: list[str] | None = None) -> int:
    mode_parser = argparse.ArgumentParser(add_help=False, argument_default=argparse.SUPPRESS)
    mode_parser.add_argument("--daily", action="store_true", help="Run daily refresh tasks")

    parser = argparse.ArgumentParser(description="Sync Morphe bundles and projects", parents=[mode_parser])
    commands = parser.add_subparsers(dest="task", help="Run one task instead of the full sync")
    for task in ("discover", "fetch", "update"):
        commands.add_parser(task, parents=[mode_parser] if task != "discover" else [])
    notification = commands.add_parser("telegram", help="Send a Telegram notification")
    notification.add_argument("title", nargs="?", help="Notification title")
    notification.add_argument("filepath", nargs="?", type=Path, default=WHATS_NEW_PATH, help="Markdown file to send")
    args = parser.parse_args(argv)
    daily = getattr(args, "daily", False)
    if args.task in ("discover", "telegram") and daily:
        parser.error(f"{args.task} does not accept --daily")

    load_dotenv(SCRIPTS_DIR / ".env", override=True)
    with http.HTTP_CLIENT:
        if args.task == "telegram":
            telegram.send_notification(args.title, args.filepath)
            return 0

        if args.task in (None, "discover"):
            result = discover.run()
            if result or args.task == "discover":
                return result

        if args.task in (None, "fetch"):
            fetch.fetch_all_repos(daily)
            if args.task == "fetch":
                return 0

        if args.task is None and daily:
            append_step_summary(f"## 🔎 Discovery:\n\n{audit_readme.audit_repos_and_links()}\n\n{find_projects.run()}")

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
