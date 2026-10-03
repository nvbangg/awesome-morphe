# Copyright (c) 2026 nvbangg (github.com/nvbangg)

from concurrent.futures import ThreadPoolExecutor, as_completed

from google_play_scraper import app as gplay_app
from google_play_scraper.exceptions import NotFoundError

from updater import normalize_image_url
from utils import CONCURRENCY, OFFICIAL_BUNDLES_PATH, load_json


def fetch_app_details(package_name: str) -> tuple[dict | None, bool]:
    try:
        result = gplay_app(package_name, lang="en", country="us")
        if not result:
            return None, False
        icon_url = normalize_image_url(result.get("icon"))
        desc = result.get("summary") or ""
        categories = result.get("categories") or []
        category = (
            result.get("genre")
            or (categories[0].get("name") if categories else "")
            or ""
        )
        details = {
            "name": result.get("title"),
            "iconUrl": icon_url,
            "description": desc,
            "minInstalls": result.get("minInstalls") or 0,
            "category": category,
        }
        return details, False
    except NotFoundError:
        return None, True
    except Exception as error:
        print(f"[-] Error fetching Google Play details for {package_name}: {error}")
        return None, False


def process(apps_dict: dict, mode: str) -> None:
    official_data = load_json(OFFICIAL_BUNDLES_PATH, {})
    official_store = (
        official_data.get("store", {}) if isinstance(official_data, dict) else {}
    )

    if mode == "weekly":
        apps_to_scrape = list(apps_dict.keys())
    else:
        apps_to_scrape = [
            package_name
            for package_name, app_data in apps_dict.items()
            if any(
                app_data.get(field) is None
                for field in (
                    "name",
                    "iconUrl",
                    "description",
                    "minInstalls",
                    "category",
                )
            )
        ]
    if apps_to_scrape:
        print(
            f"\nScraping Google Play for {len(apps_to_scrape)} apps (mode: {mode})..."
        )
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
            future_to_package = {
                executor.submit(fetch_app_details, package_name): package_name
                for package_name in apps_to_scrape
            }
            for future in as_completed(future_to_package):
                package_name = future_to_package[future]
                try:
                    details, is_404 = future.result()
                    current_app = apps_dict[package_name]
                    if not is_404 and details:
                        for key, value in details.items():
                            if value is not None:
                                current_app[key] = value
                        for field in ("name", "iconUrl", "description"):
                            if current_app.get(field) is None:
                                current_app[field] = ""
                    elif is_404:
                        current_app["minInstalls"] = 0
                        current_app["category"] = ""
                        for field in ("name", "iconUrl", "description"):
                            if current_app.get(field) is None:
                                current_app[field] = ""
                except Exception as error:
                    print(f"[-] Error processing {package_name}: {error}")
    print(
        f"\nSyncing with official store data ({len(official_store)} apps in store)..."
    )
    for package_name, app_data in apps_dict.items():
        official_app = official_store.get(package_name)
        if official_app:
            for field_name in ("name", "iconUrl", "description"):
                field_value = official_app.get(field_name)
                if field_value:
                    app_data[field_name] = field_value

    for app_data in apps_dict.values():
        if app_data.get("iconUrl"):
            app_data["iconUrl"] = normalize_image_url(app_data["iconUrl"])
