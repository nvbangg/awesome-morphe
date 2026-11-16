# Copyright (c) 2026 nvbangg (github.com/nvbangg)

from concurrent.futures import ThreadPoolExecutor

from common.config import (
    CONCURRENCY,
    PROJECTS_DIR,
    README_REPOS_PATH,
    UNAVAILABLE_HTTP_CODES,
)
from common.files import load_lines
from common.http import check_link_status
from common.repositories import build_repo_url, fetch_repo_details, parse_repo_url
from common.summary import format_summary_section


def audit_repos_and_links() -> str:
    repo_urls = load_lines(README_REPOS_PATH)
    link_urls = load_lines(PROJECTS_DIR / "readme-links.txt")
    print(
        f"Auditing {len(repo_urls)} repositories and {len(link_urls)} links from README..."
    )

    issues: list[str] = []
    other_errors: list[str] = []

    if repo_urls:
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
            for url, details in zip(
                repo_urls, executor.map(fetch_repo_details, repo_urls), strict=True
            ):
                if details.get("is_404"):
                    issues.append(f"{url}: 404 Not Found")
                elif details.get("is_451"):
                    issues.append(f"{url}: 451 Unavailable For Legal Reasons")
                elif details.get("is_archived"):
                    issues.append(f"{url}: Repository is archived")
                elif full_name := details.get("full_name"):
                    source, original_repo = parse_repo_url(url)
                    if (
                        source
                        and original_repo
                        and full_name.lower() != original_repo.lower()
                    ):
                        issues.append(f"{url} -> {build_repo_url(source, full_name)}")
                elif details.get("error"):
                    other_errors.append(f"{url}: {details['error']}")

    if link_urls:
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
            for url, status in zip(
                link_urls, executor.map(check_link_status, link_urls), strict=True
            ):
                if (
                    status.get("is_dead")
                    or status.get("status_code") in UNAVAILABLE_HTTP_CODES
                ):
                    issues.append(f"{url}: {status.get('error', 'Dead')}")
                elif status.get("is_redirect"):
                    issues.append(f"{url} -> {status.get('final_url', '')}")
                elif status.get("error"):
                    other_errors.append(f"{url}: {status['error']}")

    print(f"Audited {len(repo_urls)} repositories and {len(link_urls)} links.")

    summary_sections = (
        ["\n".join(f"- {issue}" for issue in sorted(issues))] if issues else []
    )
    if other_errors:
        details = format_summary_section(
            "Other errors",
            "\n".join(f"- {error}" for error in sorted(other_errors)),
            heading_level=None,
            collapsed=True,
        )
        summary_sections.append("- " + details.replace("\n", "\n  "))
    if not issues and not other_errors:
        summary_sections.append("All repositories and links are active.")

    return format_summary_section(
        "README audit", "\n\n".join(summary_sections), len(issues) + len(other_errors)
    )
