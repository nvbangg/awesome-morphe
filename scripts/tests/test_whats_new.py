from common.utils import PACKAGE_UNIVERSAL
from updater import whats_new


def build_history(catalog: dict) -> dict:
    history = {}
    for bundle in catalog["bundles"]:
        bundle_apps = {}
        for patch_data in bundle["patches"]:
            whats_new.collect_patch_history(
                bundle_apps, patch_data["name"], patch_data.get("compatiblePackages")
            )
        history[f"https://{bundle['source']}.com/{bundle['repo']}"] = {
            package_name: sorted(patches)
            for package_name, patches in bundle_apps.items()
        }
    return history


def make_catalog() -> dict:
    return {
        "bundles": [
            {
                "source": source,
                "repo": "owner/alpha",
                "name": source.title(),
                "hotRank": index,
                "patches": [{"name": source + " patch"}],
            }
            for index, source in enumerate(("github", "gitlab"))
        ],
        "store": {},
    }


def test_baseline_and_diff_preserve_both_hosts() -> None:
    catalog = make_catalog()
    baseline = build_history(catalog)
    assert set(baseline) == {
        "https://github.com/owner/alpha",
        "https://gitlab.com/owner/alpha",
    }
    names, order = whats_new.extract_bundle_metadata(catalog["bundles"])
    assert len(names) == 2
    changes = whats_new.build_json_diff({}, baseline, {}, order)
    markdown = whats_new.generate_markdown(changes, {}, {}, names, order)
    assert "github=owner/alpha" in markdown
    assert "gitlab=owner/alpha" in markdown
    assert "github=https" not in markdown
    assert whats_new.build_json_diff(baseline, baseline, {}, order) == {}


def test_missing_bundle_name_uses_the_repository_name() -> None:
    catalog = make_catalog()
    for bundle in catalog["bundles"]:
        bundle.pop("name")
    names, order = whats_new.extract_bundle_metadata(catalog["bundles"])
    assert set(names.values()) == {"alpha"}
    changes = whats_new.build_json_diff({}, build_history(catalog), {}, order)
    markdown = whats_new.generate_markdown(changes, {}, {}, {}, order)
    assert "github=owner/alpha" in markdown
    assert "gitlab=owner/alpha" in markdown


def test_missing_install_count_does_not_break_changelog_sorting() -> None:
    key = whats_new.get_app_sort_key(
        "com.test.app", {"com.test.app": {"name": "Test", "minInstalls": None}}
    )
    assert key[1] == 0


def test_patch_history_filters_packages_deduplicates_and_keeps_universal() -> None:
    bundle_apps = {}
    compatibility = [
        {"packageName": "com.test.app"},
        {"packageName": "com.test.app"},
        {"packageName": "com.example.app"},
        {"packageName": "invalid"},
    ]
    whats_new.collect_patch_history(bundle_apps, "Patch", compatibility)
    whats_new.collect_patch_history(bundle_apps, "Patch", compatibility)
    whats_new.collect_patch_history(bundle_apps, "Universal patch", None)
    whats_new.collect_patch_history(
        bundle_apps, "Template patch", [{"packageName": "com.example.app"}]
    )
    assert bundle_apps == {
        "com.test.app": {"Patch"},
        PACKAGE_UNIVERSAL: {"Universal patch", "Template patch"},
    }
