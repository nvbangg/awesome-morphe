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


def main(argv: list[str] | None = None) -> int:
    mode_parser = argparse.ArgumentParser(add_help=False, argument_default=argparse.SUPPRESS)
    modes = mode_parser.add_mutually_exclusive_group()
    modes.add_argument("--daily", action="store_true", help="Run daily refresh tasks")
    modes.add_argument("--weekly", action="store_true", help="Run weekly refresh tasks")

    parser = argparse.ArgumentParser(description="Sync Morphe bundles and projects", parents=[mode_parser])
    commands = parser.add_subparsers(dest="task", help="Run one task instead of the full sync")
    for task in ("discover", "fetch", "update"):
        commands.add_parser(task, parents=[mode_parser])
    notification = commands.add_parser("telegram", help="Send a Telegram notification")
    notification.add_argument("title", nargs="?", help="Notification title")
    notification.add_argument("filepath", nargs="?", type=Path, default=WHATS_NEW_PATH, help="Markdown file to send")
    args = parser.parse_args(argv)
    daily = getattr(args, "daily", False)
    weekly = getattr(args, "weekly", False)
    if daily and weekly:
        parser.error("--daily and --weekly cannot be used together")
    if args.task == "telegram" and (daily or weekly):
        parser.error("telegram does not accept --daily or --weekly")

    mode = "weekly" if weekly else "daily" if daily else "default"
    load_dotenv(SCRIPTS_DIR / ".env", override=True)
    with http.HTTP_CLIENT:
        if args.task == "telegram":
            telegram.send_notification(args.title, args.filepath)
            return 0

        if args.task in (None, "discover"):
            result = discover.run(daily, weekly)
            if result or args.task == "discover":
                return result

        if args.task in (None, "fetch"):
            fetch.fetch_all_repos(daily, weekly)
            if args.task == "fetch":
                return 0

        if (
            args.task is None
            and mode == "default"
            and not subprocess.check_output(
                ["git", "status", "--porcelain", "--", "data/", "web/public/"], cwd=ROOT_DIR
            )
        ):
            return 0

        result = update.run(mode)
        if result == 0 and (output_path := os.environ.get("GITHUB_OUTPUT")):
            with Path(output_path).open("a", encoding="utf-8") as file:
                file.write("updated=true\n")
        return result


if __name__ == "__main__":
    sys.exit(main())
