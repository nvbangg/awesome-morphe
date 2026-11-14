import contextlib
import json
import os
from pathlib import Path
from typing import Any


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


def load_json(path: str | Path, default: Any = None) -> Any:
    path = Path(path)
    if path.exists():
        with (
            contextlib.suppress(OSError, json.JSONDecodeError),
            path.open(encoding="utf-8") as file,
        ):
            return json.load(file)
    return default if default is not None else {}


def save_json(path: str | Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
        file.write("\n")


def load_lines(path: str | Path) -> list[str]:
    path = Path(path)
    if not path.exists():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
