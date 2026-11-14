from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
SCRIPTS_DIR = ROOT_DIR / "scripts"
PUBLIC_DIR = ROOT_DIR / "web" / "public"

BUNDLE_SOURCES_DIR = DATA_DIR / "bundle-sources"
BUNDLES_DIR = DATA_DIR / "bundles"
PATCHES_DIR = DATA_DIR / "patches"
PROJECTS_DIR = DATA_DIR / "projects"
REPOS_JSON_PATH = DATA_DIR / "repos.json"
OFFICIAL_BUNDLES_PATH = DATA_DIR / "official-bundles.json"

WHATS_NEW_PATH = SCRIPTS_DIR / "temp" / "whats-new.md"
README_REPOS_PATH = PROJECTS_DIR / "readme-repos.txt"

DEFAULT_BRANCHES = ("main", "dev")
PACKAGE_UNIVERSAL = "__universal__"
PACKAGE_EXAMPLE = "com.example.app"

CONCURRENCY = 8
PROJECT_USER_AGENT = "AwesomeMorphe/1.0 (+https://github.com/nvbangg/awesome-morphe)"

UNAVAILABLE_HTTP_CODES = (404, 451)
DEAD_LINK_HTTP_CODES = (404, 410)
