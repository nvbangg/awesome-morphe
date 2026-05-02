# Copyright (c) 2026 nvbangg (github.com/nvbangg)

import json
from pathlib import Path

ROOT = Path.cwd()
SRC_DIR = ROOT / "src"
BUNDLES_DIR = ROOT / "patch-bundles"
STABLE_OUT = SRC_DIR / "sources-stable.json"
LATEST_OUT = SRC_DIR / "sources-latest.json"
APP_NAMES_PATH = SRC_DIR / "app-names.json"
CHANGELOG_PATH = ROOT / "changelog.md"
CHANGELOG_PRE_PATH = ROOT / "changelog-pre-release.md"


def read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf8"))
    except FileNotFoundError:
        return default


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf8")


def get_info_bundle(bundle_json):
    download_url = bundle_json["download_url"].split("/")
    return "/".join(download_url[3:5]), download_url[7], bundle_json.get("created_at", "")


def collect_apps(list_json, app_names):
    apps = set()
    for patch in list_json.get("patches") or []:
        compatible = patch.get("compatiblePackages")
        if isinstance(compatible, dict):
            # Old format: dict of package names
            apps.update(compatible.keys())
        elif isinstance(compatible, list):
            # New format: list of objects
            for entry in compatible:
                if isinstance(entry, dict):
                    pkg = entry.get("packageName")
                    if pkg:
                        apps.add(pkg)
                        app_name = entry.get("name")
                        if app_name and app_names.get(pkg) != app_name:
                            app_names[pkg] = app_name
    return sorted(apps)


# Inspired by code from Paresh Maheshwari
def derive_name(pkg):
    skip = {"com", "org", "net", "android", "app", "apps", "player", "client", "mobile", "thirdpartyclient"}
    parts = [p for p in pkg.split(".") if p not in skip and len(p) > 1]
    name = parts[-1] if parts else pkg.split(".")[-1]
    return name.replace("-", " ").replace("_", " ").title()


def format_app(pkg, app_names, source_key, label):
    name = app_names.get(pkg) or derive_name(pkg)
    url = f"https://nvbangg.github.io/awesome-for-morphe/?source={source_key}&app={pkg}"
    if label == "pre-release":
        url += "&channel=latest"
    return f"- [{name}]({url})"


def build_notes(label, old_sources, new_sources, app_names):
    new_bundles, new_apps_groups = [], []
    for key in sorted(new_sources.keys()):
        entry = new_sources.get(key) or {}
        apps = entry.get("apps") or []
        if key not in old_sources:
            url = f"https://nvbangg.github.io/awesome-for-morphe/?source={key}"
            if label == "pre-release":
                url += "&channel=latest"
            link = f"[{key}]({url})"
            new_bundles.append(f"- {link}")
        old_apps = set(old_sources.get(key, {}).get("apps") or [])
        added = [pkg for pkg in apps if pkg not in old_apps]
        if added:
            heading = f"## {key}"
            new_apps_groups.append("\n".join([heading] + [format_app(p, app_names, key, label) for p in added]))
    sections = []
    if new_bundles:
        sections.append(f"# 🧩 New Patch Sources ({label})\n" + "\n".join(new_bundles))
    if new_apps_groups:
        sections.append(f"# 📱 New Apps ({label})\n" + "\n\n".join(new_apps_groups))
    return "\n\n".join(sections)


def build_sources(app_names):
    stable, latest = {}, {}
    for bundle_dir in sorted(BUNDLES_DIR.iterdir()):
        if not bundle_dir.is_dir():
            continue
        base = bundle_dir.name.removesuffix("-patch-bundles")
        for channel, out in (("stable", stable), ("latest", latest)):
            bundle_path = bundle_dir / f"{base}-{channel}-patches-bundle.json"
            list_path = bundle_dir / f"{base}-{channel}-patches-list.json"
            bundle_json = read_json(bundle_path)
            list_json = read_json(list_path)
            if not bundle_json or not list_json:
                continue
            repo, tag, created_at = get_info_bundle(bundle_json)
            if not repo:
                continue
            out[base] = {
                "repo": repo,
                "tag": tag,
                "created_at": created_at,
                "apps": collect_apps(list_json, app_names),
            }

    return dict(sorted(stable.items())), dict(sorted(latest.items()))


def main():
    if not BUNDLES_DIR.exists() or not any(BUNDLES_DIR.iterdir()):
        raise SystemExit("patch-bundles/ is empty — run download-patch-bundles.py first")

    old_stable = read_json(STABLE_OUT, {}) or {}
    old_latest = read_json(LATEST_OUT, {}) or {}
    app_names = read_json(APP_NAMES_PATH, {}) or {}

    new_stable, new_latest = build_sources(app_names)

    write_json(STABLE_OUT, new_stable)
    write_json(LATEST_OUT, new_latest)
    write_json(APP_NAMES_PATH, app_names)

    is_first_run = not any(e.get("apps") for e in old_stable.values())
    if is_first_run:
        print("Initialized sources.")
        return

    # Stable changelog: new_stable vs old_stable
    stable_notes = build_notes("stable", old_stable, new_stable, app_names)
    if stable_notes:
        CHANGELOG_PATH.write_text(stable_notes + "\n", encoding="utf8")
        print("Stable changelog created.")

    # Pre-release changelog: new_latest vs (new_stable + old_latest)
    pre_baseline = {}
    for key in set(new_stable) | set(old_latest):
        stable_apps = set((new_stable.get(key) or {}).get("apps") or [])
        prev_apps = set((old_latest.get(key) or {}).get("apps") or [])
        repo = ((new_stable.get(key) or old_latest.get(key)) or {}).get("repo")
        pre_baseline[key] = {"repo": repo, "apps": sorted(stable_apps | prev_apps)}

    pre_notes = build_notes("pre-release", pre_baseline, new_latest, app_names)
    if pre_notes:
        CHANGELOG_PRE_PATH.write_text(pre_notes + "\n", encoding="utf8")
        print("Pre-release changelog created.")

    print("Updated sources.")


if __name__ == "__main__":
    main()
