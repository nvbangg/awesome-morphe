import os
from pathlib import Path


def format_summary_section(
    title: str,
    content: str,
    *,
    result_count: int | None = None,
    heading_level: int | None = 3,
    collapsed: bool = False,
) -> str:
    label = title if result_count is None else f"{title} ({result_count})"
    if collapsed:
        heading = (
            f"<h{heading_level}>{label}</h{heading_level}>" if heading_level else label
        )
        return f"<details>\n<summary>{heading}</summary>\n\n{content}\n\n</details>"
    heading = f"{'#' * heading_level} {label}" if heading_level else label
    return f"{heading}\n\n{content}"


def append_step_summary(markdown_content: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path and markdown_content.strip():
        with Path(summary_path).open("a", encoding="utf-8") as file:
            file.write(markdown_content.strip() + "\n\n---\n\n")
