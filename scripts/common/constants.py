from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
SCRIPTS_DIR = ROOT_DIR / "scripts"
PUBLIC_DIR = ROOT_DIR / "web" / "public"

CUSTOM_JSON_PATH = DATA_DIR / "custom.json"
BUNDLES_DIR = DATA_DIR / "bundles"
PATCHES_DIR = DATA_DIR / "patches"
PROJECTS_JSON_PATH = DATA_DIR / "projects.json"
REPOS_JSON_PATH = DATA_DIR / "repos.json"
OFFICIAL_BUNDLES_PATH = DATA_DIR / "official-bundles.json"

WHATS_NEW_PATH = SCRIPTS_DIR / "temp" / "whats-new.md"

DEFAULT_BRANCHES = ("main", "dev")
PACKAGE_UNIVERSAL = "__universal__"
PACKAGE_EXAMPLE = "com.example.app"

CONCURRENCY = 8
HTTP_TIMEOUT_SECONDS = 15
PROJECT_USER_AGENT = "AwesomeMorphe/1.0 (+https://github.com/nvbangg/awesome-morphe)"

UNAVAILABLE_HTTP_CODES = (404, 451)
DEAD_LINK_HTTP_CODES = (404, 410)
