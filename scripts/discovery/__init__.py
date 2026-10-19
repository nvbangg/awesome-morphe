from pathlib import Path

from common.utils import format_request_error, load_json, save_json


def load_provider_sources(path: Path) -> dict:
    try:
        data = load_json(path)
    except UnicodeError:
        return {}
    if not isinstance(data, dict) or not all(
        isinstance(entry, dict) for entry in data.values()
    ):
        return {}
    return data


def report_provider_warning(
    provider_name: str, reason: str | Exception, output_path: Path
) -> str:
    message = format_request_error(reason) if isinstance(reason, Exception) else reason
    saved_sources = (
        "kept saved sources"
        if load_provider_sources(output_path)
        else "no saved sources available"
    )
    warning_message = f"[{provider_name}]: {message}; {saved_sources}"
    print(f"[-] {warning_message}")
    return warning_message


def export_provider(
    provider_name: str, discovered: dict, output_path: Path
) -> str | None:
    if not discovered:
        return report_provider_warning(provider_name, "No sources found", output_path)

    save_json(
        output_path, dict(sorted(discovered.items(), key=lambda item: item[0].lower()))
    )
    print(f"[{provider_name}] Exported {len(discovered)} sources to {output_path.name}")
    return None
