import contextlib
import json
import os
from pathlib import Path
from typing import Any

SUMMARY_DETAILS_THRESHOLD = 10


def format_summary_section(
    title: str, content: str, result_count: int, *, heading_level: int = 3
) -> str:
    if result_count >= SUMMARY_DETAILS_THRESHOLD:
        content = (
            f"<details>\n<summary>Show details</summary>\n\n{content}\n\n</details>"
        )
    return f"{'#' * heading_level} {title} ({result_count})\n\n{content}"


def append_step_summary(markdown_content: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path and markdown_content.strip():
        with (
            contextlib.suppress(Exception),
            Path(summary_path).open("a", encoding="utf-8") as file,
        ):
            file.write(markdown_content.strip() + "\n\n---\n\n")


def set_step_output(name: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path and name:
        with (
            contextlib.suppress(Exception),
            Path(output_path).open("a", encoding="utf-8") as file,
        ):
            file.write(f"{name}={value}\n")


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
        if line.strip() and not line.startswith("#")
    ]
