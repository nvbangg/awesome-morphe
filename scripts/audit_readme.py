# Copyright (c) 2026 nvbangg (github.com/nvbangg)

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from repo_info import fetch_repo_details
from utils import (
    CONCURRENCY,
    README_LINKS_PATH,
    README_REPOS_PATH,
    append_step_summary,
    build_repo_url,
    check_link_status,
    load_lines,
    parse_repo_url,
)


def audit_repos_and_links() -> dict[str, list[str]]:
    repo_urls = load_lines(README_REPOS_PATH)
    link_urls = load_lines(README_LINKS_PATH)
    print(
        f"Auditing {len(repo_urls)} repositories and {len(link_urls)} links from README..."
    )

    errors: dict[str, list[str]] = {"unavailable": [], "warnings": [], "other": []}

    if repo_urls:
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
            future_to_url = {
                executor.submit(fetch_repo_details, url): url for url in repo_urls
            }
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    details = future.result()
                except Exception as error:
                    details = {"error": str(error)}

                if details.get("is_404"):
                    errors["unavailable"].append(f"{url}: 404 Not Found")
                elif details.get("is_451"):
                    errors["unavailable"].append(f"{url}: 451 DMCA Takedown")
                elif details.get("is_archived"):
                    errors["warnings"].append(f"{url}: Repository is archived")
                elif full_name := details.get("full_name"):
                    source, original_repo = parse_repo_url(url)
                    if original_repo and full_name.lower() != original_repo.lower():
                        errors["warnings"].append(
                            f"{url} -> {build_repo_url(source, full_name)}"
                        )
                elif details.get("error"):
                    errors["other"].append(f"{url}: {details['error']}")

    if link_urls:
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
            future_to_link = {
                executor.submit(check_link_status, url): url for url in link_urls
            }
            for future in as_completed(future_to_link):
                url = future_to_link[future]
                try:
                    status = future.result()
                except Exception as error:
                    status = {"error": str(error)}

                if status.get("is_dead"):
                    errors["unavailable"].append(
                        f"{url}: {status.get('error', 'Dead')}"
                    )
                elif status.get("is_redirect"):
                    errors["warnings"].append(f"{url} -> {status.get('final_url', '')}")
                elif status.get("error"):
                    errors["other"].append(f"{url}: {status['error']}")

    completed_message = (
        f"Audited {len(repo_urls)} repositories and {len(link_urls)} links."
    )
    print(completed_message)

    summary_sections = [f"## 📋 Audit Readme\n{completed_message}"]
    for category_name, category_errors in (
        ("Unavailable", errors["unavailable"]),
        ("Warnings", errors["warnings"]),
        ("Other Errors", errors["other"]),
    ):
        if category_errors:
            summary_sections.append(
                f"### {category_name} ({len(category_errors)})\n\n"
                + "\n".join(f"- {error}" for error in sorted(category_errors))
            )
    if not any(errors.values()):
        summary_sections.append("- ✅ All repositories and links are active.")

    append_step_summary("\n\n".join(summary_sections))
    return errors


def main() -> int:
    audit_repos_and_links()
    return 0


if __name__ == "__main__":
    sys.exit(main())
