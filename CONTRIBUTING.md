## [nvbangg/awesome-morphe](https://github.com/nvbangg/awesome-morphe)

<div align="center">

[![Next.js](https://img.shields.io/badge/Next.js-000000?logo=nextdotjs&logoColor=white)](https://github.com/vercel/next.js)
[![React](https://img.shields.io/badge/React-20232A?logo=react&logoColor=61DAFB)](https://github.com/react/react)
[![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white)](https://github.com/microsoft/TypeScript)
[![Node.js](https://img.shields.io/badge/Node.js-339933?logo=nodedotjs&logoColor=white)](https://github.com/nodejs/node)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-06B6D4?logo=tailwindcss&logoColor=white)](https://github.com/tailwindlabs/tailwindcss)
[![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white)](https://github.com/python/cpython)
[![Java](https://img.shields.io/badge/Java-ED8B00?logo=openjdk&logoColor=white)](https://github.com/openjdk/jdk)
[![Kotlin](https://img.shields.io/badge/Kotlin-7F52FF?logo=kotlin&logoColor=white)](https://github.com/JetBrains/kotlin)

[![pnpm](https://img.shields.io/badge/pnpm-F69220?logo=pnpm&logoColor=white)](https://github.com/pnpm/pnpm)
[![uv](https://img.shields.io/badge/uv-DE5FE9?logo=uv&logoColor=black)](https://github.com/astral-sh/uv)
[![Gradle](https://img.shields.io/badge/Gradle-02303A?logo=gradle&logoColor=white)](https://github.com/gradle/gradle)
[![Biome](https://img.shields.io/badge/Biome-60A5FA?logo=biome&logoColor=white)](https://github.com/biomejs/biome)
[![Ruff](https://img.shields.io/badge/Ruff-D7FF64?logo=ruff&logoColor=black)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/badge/ty-46EBE1?logo=ty&logoColor=black)](https://github.com/astral-sh/ty)
[![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?logo=githubactions&logoColor=white)](https://github.com/nvbangg/awesome-morphe/actions)
[![Cloudflare](https://img.shields.io/badge/Cloudflare-F38020?logo=cloudflare&logoColor=white)](https://www.cloudflare.com/)

</div>

### 🔗 Jump to:

- [📂 Project Structure](#project-structure)
- [💻 Local Development](#local-development)
  - [🌐 Website](#website)
  - [🐍 Scripts](#local-scripts)
- [🤖 Automation Workflows](#automation-workflows)
- [🛠️ Script Logic](#script-logic)
- [🌐 Website Logic](#website-logic)

> [!NOTE]
> This document describes the project structure, automation workflows, and data-processing logic behind the [Awesome Morphe Website](https://awesome-morphe.pages.dev/).

## <a id="project-structure"></a> 📂 Project Structure

```text
awesome-morphe/
├── .github/                # Automation workflows
├── data/                   # Raw fetched data, source configuration & sync state
├── scripts/                # Automated data-processing scripts
├── web/                    # Website source code
│   ├── public/
│   │   ├── bundles.json    # Metadata of all active bundles, patches & apps
│   │   └── whats-new.json  # Rolling changelog
│   └── ...
├── CONTRIBUTING.md
├── LICENSE
└── README.md
```

## <a id="local-development"></a> 💻 Local Development

### <a id="website"></a> 🌐 Website

Run the following commands from [`web/`](./web/) (`cd web` from the repository root).

#### Environment Setup

Install [Node.js](https://nodejs.org/en/download) (>= 24) then run:

```sh
npm install -g pnpm
pnpm install --frozen-lockfile
pnpm exec playwright install chromium
```

#### Running

Run the development server:

```sh
pnpm dev
```

#### Checks

Check formatting, lint, types, and run unit and desktop/mobile browser tests:

```sh
pnpm check
pnpm test
pnpm test:e2e
```

### <a id="local-scripts"></a> 🐍 Scripts

Run the following commands from [`scripts/`](./scripts/) (`cd scripts` from the repository root).

#### Environment Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) then run:

```sh
uv sync --locked
cp .env.example .env
```

Configure `.env` as described in [`.env.example`](./scripts/.env.example).

Install [JDK 21](https://www.oracle.com/java/technologies/downloads/#java21) to parse bundles without `patches-list.json`. Set `JAVA_HOME` in `.env` to its installation directory if needed.

Bundle parsing also requires `GITHUB_ACTOR` and a `GITHUB_TOKEN` with `read:packages` for GitHub Packages access.

For GitHub Actions, add the corresponding values to repository secrets as needed.

#### Running

[`main.py`](./scripts/main.py) is the single CLI entry point for normal or daily sync and individual tasks. It automatically loads `scripts/.env`, overriding inherited environment variables for the script and its child processes.

| Command | Purpose |
| --- | --- |
| `uv run main.py` | Run normal sync |
| `uv run main.py --daily` | Run daily sync |
| `uv run main.py audit-readme` | Audit README repositories and links |
| `uv run main.py find-projects` | Find new projects |
| `uv run main.py discover` | Discover bundle sources |
| `uv run main.py fetch` | Fetch bundle data |
| `uv run main.py fetch --daily` | Fetch with daily checks |
| `uv run main.py update` | Update catalog and app metadata |
| `uv run main.py update --daily` | Update with daily refresh and changelog generation |
| `uv run main.py telegram` | Send Telegram notification |

Use `uv run main.py --help` or `uv run main.py COMMAND --help` for available arguments.

#### Checks

Check formatting, lint, types, and run tests:

```sh
uv run ruff check --fix .
uv run ruff format .
uv run ty check
uv run pytest
```

## <a id="automation-workflows"></a> 🤖 Automation Workflows

### [Sync Workflow](../../actions/workflows/sync.yml) ([sync.yml](./.github/workflows/sync.yml))

[`ci.yml`](./.github/workflows/ci.yml) (triggered by a Cloudflare Worker every 3 hours) selects `daily` until a daily sync succeeds for the current UTC day, then `normal`. It triggers [`sync.yml`](./.github/workflows/sync.yml) with the selected mode.

```mermaid
flowchart TD
    Mode{"sync.yml: Mode?"}
    Mode -->|daily| Audit["Audit README repositories and links"]
    Audit --> Projects["Find new projects"]
    Mode -->|normal| Discover["Discover bundle sources"]
    Projects --> Discover
    Discover --> Fetch["Fetch bundle data"]
    Fetch --> Changed{"Daily or data changed?"}
    Changed -->|Yes| Update["Update catalog and app metadata"]
    Changed -->|No| Commit
    Update --> WhatsNew["Generate What's New (daily only)"]
    WhatsNew --> Commit["Commit and push"]
    Commit --> Daily{"Daily?"}
    Daily -->|Yes| Telegram["Send Telegram notification"]
    Telegram --> Cleanup["Clean old workflow runs"]
    Cleanup --> Done(["Complete"])
    Daily -->|No| Done
```

## <a id="script-logic"></a> 🛠️ Script Logic

Core automation scripts are written in Python under [`scripts/`](./scripts/).

```text
scripts/
├── main.py                 # Run sync tasks
├── discover.py             # Discover bundle sources
├── fetch.py                # Fetch bundle data
├── update.py               # Update catalog and app metadata
├── audit_readme.py         # Audit README repositories and links
├── find_projects.py        # Find new projects
├── telegram.py             # Send Telegram notification
└── ...                     # Other supporting files and directories
```

### Discover bundle sources ([discover.py](./scripts/discover.py))

Collects bundle sources from the providers below, combines them with manual configuration, and saves the list to [`data/discovery.json`](./data/discovery.json). If a provider is unavailable or returns no sources, its saved list is kept.

#### Discovered Sources

- Custom sources in [`data/custom.json`](./data/custom.json)
- [Morphe Community Patches](https://morphe-patches.software)
- [Jman's Patch Bundle Registry](https://github.com/Jman-Github/Patch-Bundle-Registry)
- [Morphe Archive](https://github.com/rushiforai/morphe-archive)

#### Custom Configuration

Add sources to [`data/custom.json`](./data/custom.json), or set `enabled: false` to exclude them.

```json
{
  "https://github.com/owner/repo-to-add": {},
  "https://gitlab.com/owner/repo-to-exclude": {
    "enabled": false
  },
  "https://gitlab.com/disabled-owner": {
    "enabled": false
  }
}
```

### Fetch bundle data ([fetch.py](./scripts/fetch.py))

```mermaid
flowchart TD
    Sources["data/discovery.json"] --> Metadata["Refresh repository metadata & check main/dev manifests"]
    Metadata --> Changed{"Manifest changed or local JSON files missing?"}
    Changed -->|Yes| Download["Validate download URL & download .mpp"]
    Download --> PatchList["Fetch patches-list.json & save bundle files"]
    Changed -->|No| Daily{"--daily?"}
    PatchList --> Daily
    Daily -->|Yes| Verify["Check .mpp URLs not already downloaded"]
    Verify --> Missing{"Patch list missing (HTTP 404)?"}
    Daily -->|No| Missing
    Missing -->|Yes| Parser["Generate missing patch lists with Kotlin parser"]
    Parser --> Images{"--daily?"}
    Missing -->|No| Images
    Images -->|Yes| CheckImages["Check bundle images"]
    CheckImages --> State["Save repository state to data/repos.json"]
    Images -->|No| State
```

Disabled repositories are skipped. Temporary errors keep saved data; unavailable or invalid branches are excluded.

### Update catalog and app metadata ([update.py](./scripts/update.py))

```mermaid
flowchart TD
    Local["Read repository metadata & local bundle data"] --> Branch{"Valid dev is newer or no valid main?"}
    Branch -->|Yes| Dev["Use dev"]
    Branch -->|No| Main["Use main"]
    Dev --> Prepare["Process selected patches & mark prereleases"]
    Main --> Prepare
    Prepare --> Daily{"--daily?"}
    Daily -->|Yes| Refresh["Refresh all Google Play app metadata"]
    Daily -->|No| Missing["Fetch missing Google Play app metadata"]
    Refresh --> Official["Apply app metadata from data/official-bundles.json"]
    Missing --> Official
    Official --> Catalog["Write web/public/bundles.json"]
    Catalog --> Changelog{"--daily?"}
    Changelog -->|Yes| News["Generate What's New content"]
    News --> State["Save app hashes & history to data/state.json"]
    Changelog -->|No| State
```

Disabled repositories and bundles without valid branch data are skipped.

Bundle names use `main`, then `dev`. Bundles without valid `main` data and dev-only patches are prereleases; apps are prerelease only if all their patches are.

*History and bundle files use repository IDs to preserve data and prevent duplicate announcements when repositories are renamed or bundles return.*

### Audit README repositories and links ([audit_readme.py](./scripts/audit_readme.py))

Reports unavailable or archived repositories, repository renames, and broken or redirected links from [`data/projects.json`](./data/projects.json) for review.

### Find new projects ([find_projects.py](./scripts/find_projects.py))

Finds standalone Morphe projects on GitHub and saves candidates to `newRepos` in [`data/projects.json`](./data/projects.json) for review. Skips repositories in `readmeRepos` or `excludedRepos`.

### Send Telegram notification ([telegram.py](./scripts/telegram.py))

Sends Markdown using `TG_TOKEN` and `TG_CHAT`. Skips missing or empty files.

- **Default:** Sends `scripts/temp/whats-new.md`, titled `🔔 What's New (Month Day)`.
- **`"Custom Title"`:** Sets the title.
- **`"Custom Title" "path/to/file.md"`:** Sets the title and input file.

## <a id="website-logic"></a> 🌐 Website Logic

Loads the catalog from [`web/public/bundles.json`](./web/public/bundles.json) and What's New from [`web/public/whats-new.json`](./web/public/whats-new.json).

### Sorting

#### Apps

- **Default:** Most Google Play installs, then most patches, then name. Universal patches stay last.
- Other sorts: newest, updated, patch count, or name. Ties use the default order. Recently updated uses the latest patch change recorded for each app.

#### Bundles

- **Default:** Uses the [Morphe Hot ranking](https://morphe-patches.software/), with `MorpheApp/morphe-patches` first. Remaining bundles updated within 30 days are sorted by stars then update time; older bundles follow, sorted by update time then stars. This order is stored as `hotRank`.
- Other sorts: newest, updated, stars, app count, patch count, or name. Ties use the default order.

#### Patches

Patches first seen within seven days are sorted newest first, followed by older patches in their original order.

### Search and Filters

All search words must match. Matching ignores case, accents, and punctuation.

- **Apps:** Name, package name, and description.
- **Bundles:** Name, source, and repository.
- **Details:** App/bundle names, package/repository names, patch text, and options.

Apps filter by Google Play category or "Not on Google Play"; bundles by official/unofficial status.

### Status Labels

- **New:** First seen within seven days.
- **Pre-release:** Uses prerelease bundle or patch data; applies to an app only when all its patches are prerelease.
- **Unofficial:** Not in the official bundle list.
- **Archived:** Repository is archived.
- **off:** Patch is disabled by default.

### URL Navigation

Pages: `/` (or `/apps`), `/bundles`, and `/whats-new`. Query parameters control sorting and filters (`?sort=stars&category=official`) and open details:

- `?app=package.name` opens an app.
- `?github=owner/repo` or `?gitlab=owner/repo` opens a bundle.
- `?patch=patch-name` searches patches in the open detail view.

### Test Bundle

Previews `patches-list.json` from `main` and `dev` on GitHub or GitLab. Does not parse `.mpp` files or add bundles to the catalog.
