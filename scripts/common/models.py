from typing import Annotated, Any, NotRequired, TypedDict

from pydantic import Field, OnErrorOmit, TypeAdapter, with_config

NonEmptyString = Annotated[str, Field(min_length=1)]


@with_config(strict=True, extra="allow")
class BundleManifest(TypedDict):
    download_url: NonEmptyString
    created_at: NotRequired[int | float | str | None]


@with_config(strict=True, extra="allow")
class Patch(TypedDict):
    name: Annotated[str, Field(pattern=r"\S")]
    description: NotRequired[str | None]
    default: NotRequired[bool]
    use: NotRequired[bool]
    isPreRelease: NotRequired[bool]
    options: NotRequired[list[Any] | None]
    compatiblePackages: NotRequired[dict[str, Any] | list[Any] | None]


@with_config(strict=True)
class PatchList(TypedDict):
    patches: list[Any]


@with_config(strict=True, extra="allow")
class SourceConfig(TypedDict, total=False):
    enabled: bool
    revancedStars: int
    note: str
    request: str


@with_config(strict=True)
class BundleSource(TypedDict):
    source: NonEmptyString
    repo: NonEmptyString


@with_config(strict=True)
class OfficialCatalog(TypedDict):
    bundles: list[OnErrorOmit[BundleSource]]


@with_config(strict=True)
class JmanSource(TypedDict):
    patches: str
    disabled: NotRequired[bool]


@with_config(strict=True, extra="allow")
class RepositoryState(TypedDict, total=False):
    main: str | None
    dev: str | None
    image: str | None
    name: str | None
    description: str
    avatarUrl: str
    stars: int
    isArchived: bool
    renamedTo: str


@with_config(strict=True)
class RepositoryAvatar(TypedDict, total=False):
    avatar_url: str | None


@with_config(strict=True)
class GitHubRepository(TypedDict):
    full_name: NonEmptyString
    stargazers_count: NotRequired[int]
    description: NotRequired[str | None]
    owner: NotRequired[RepositoryAvatar]
    archived: NotRequired[bool]


@with_config(strict=True)
class GitLabRepository(TypedDict):
    path_with_namespace: NonEmptyString
    archived: bool
    id: NotRequired[int]
    star_count: NotRequired[int]
    description: NotRequired[str | None]
    avatar_url: NotRequired[str | None]
    namespace: NotRequired[RepositoryAvatar | None]


BUNDLE_MANIFEST = TypeAdapter(BundleManifest)
PATCH = TypeAdapter(Patch)
PATCH_LIST = TypeAdapter(PatchList)
SOURCES = TypeAdapter(dict[str, SourceConfig])
OFFICIAL_CATALOG = TypeAdapter(OfficialCatalog)
JMAN_SOURCES = TypeAdapter(dict[str, OnErrorOmit[JmanSource]])
REPOSITORIES = TypeAdapter(dict[str, RepositoryState])
APP_HASHES = TypeAdapter(dict[str, dict[str, str]], config={"strict": True})
HISTORY = TypeAdapter(dict[str, dict[str, list[str]]], config={"strict": True})
GITHUB_REPOSITORY = TypeAdapter(GitHubRepository)
GITLAB_REPOSITORY = TypeAdapter(GitLabRepository)
