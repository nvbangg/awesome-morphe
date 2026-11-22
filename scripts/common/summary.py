import os
from pathlib import Path
from typing import Literal


def format_summary_section(
    title: str,
    content: str,
    result_count: int | None = None,
    heading_level: int | None = 3,
    display: Literal["normal", "details", "details-open"] = "details",
) -> str:
    label = title if result_count is None else f"{title} ({result_count})"
    if display != "normal":
        heading = f"<h{heading_level}>{label}</h{heading_level}>" if heading_level else label
        open_attribute = " open" if display == "details-open" else ""
        return f"<details{open_attribute}>\n<summary>{heading}</summary>\n\n{content}\n\n</details>"
    heading = f"{'#' * heading_level} {label}" if heading_level else label
    return f"{heading}\n\n{content}"


def append_step_summary(markdown_content: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path and (content := markdown_content.strip()):
        with Path(summary_path).open("a", encoding="utf-8") as file:
            file.write(content + "\n\n---\n\n")
