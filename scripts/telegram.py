# Copyright (c) 2026 nvbangg (github.com/nvbangg)

import html
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

from common.utils import WHATS_NEW_PATH


def format_inline_markdown(text: str) -> str:
    escaped_text = html.escape(text)
    escaped_text = re.sub(r"~~(.*?)~~", r"<s>\1</s>", escaped_text)
    escaped_text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", escaped_text)
    escaped_text = re.sub(r"\*(.*?)\*", r"<b>\1</b>", escaped_text)
    escaped_text = re.sub(r"`(.*?)`", r"<code>\1</code>", escaped_text)
    return re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<i>\1</i>", escaped_text)


def convert_to_html(text: str) -> str:
    links: list[tuple[str, str]] = []

    def save_link(link_match: re.Match) -> str:
        link_index = len(links)
        links.append((link_match.group(1), link_match.group(2)))
        return f"\x00LINK_{link_index}\x00"

    text_with_placeholders = re.sub(
        r"\[((?:\[[^\]]*\]|[^\]])+)\]\((https?://[^\s()]+(?:\([^\s()]+\)[^\s()]*)*)\)",
        save_link,
        text,
    )

    formatted_text = format_inline_markdown(text_with_placeholders)
    for link_index, (link_text, url_string) in enumerate(links):
        formatted_link_text = format_inline_markdown(link_text)
        quoted_url = urllib.parse.quote(url_string, safe=":/%#?=&@+$,-_.!~*'()")
        formatted_text = formatted_text.replace(
            f"\x00LINK_{link_index}\x00",
            f'<a href="{quoted_url}">{formatted_link_text}</a>',
        )
    return formatted_text


def main() -> None:
    current_time = datetime.now(UTC) + timedelta(hours=1)
    formatted_date = f"{current_time.strftime('%B')} {current_time.day}"
    title = sys.argv[1] if len(sys.argv) >= 2 else f"🔔 What's New ({formatted_date})"
    filepath = Path(sys.argv[2]) if len(sys.argv) >= 3 else WHATS_NEW_PATH

    if not filepath.exists() or not (
        content := filepath.read_text(encoding="utf-8").strip()
    ):
        print(f"File {filepath} not found or empty, skipping notification.")
        return

    lines = [
        line.lstrip("# ") if line.startswith("#") else line
        for line in content.splitlines()
    ]
    formatted_content = convert_to_html("\n".join(lines).strip())
    formatted_title = f"<b>{html.escape(title)}</b>"

    token = os.environ.get("TG_TOKEN")
    chat_id = os.environ.get("TG_CHAT")
    if not token or not chat_id:
        raise SystemExit(
            "Error: TG_TOKEN or TG_CHAT environment variables are not set."
        )

    request_data = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": f"{formatted_title}\n\n{formatted_content}",
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")

    api_request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=request_data,
        method="POST",
    )
    try:
        with urllib.request.urlopen(api_request):
            print("Telegram notification sent successfully.")
    except Exception as error:
        raise SystemExit(f"Failed to send Telegram notification: {error}") from error


if __name__ == "__main__":
    main()
