from typing import Annotated, NotRequired, TypedDict

from pydantic import Field, OnErrorOmit, TypeAdapter, with_config

NonEmptyString = Annotated[str, Field(min_length=1)]
RepositoryId = Annotated[str, Field(pattern=r"^(github|gitlab):[1-9]\d*$")]


@with_config(strict=True, extra="allow")
class BundleManifest(TypedDict):
    download_url: NonEmptyString
    created_at: NotRequired[int | float | str | None]


@with_config(strict=True, extra="allow")
class PatchOption(TypedDict):
    key: str
    title: NotRequired[str | None]
    description: NotRequired[str | None]


@with_config(strict=True, extra="allow")
class PatchVersion(TypedDict):
    version: str | None


@with_config(strict=True, extra="allow")
class PatchCompatibility(TypedDict):
    packageName: str
    name: NotRequired[str | None]
    targets: NotRequired[list[str | PatchVersion] | None]


@with_config(strict=True, extra="allow")
class Patch(TypedDict):
    name: Annotated[str, Field(pattern=r"\S")]
    description: NotRequired[str | None]
    default: NotRequired[bool]
    use: NotRequired[bool]
    isPreRelease: NotRequired[bool]
    options: NotRequired[list[PatchOption] | None]
    compatiblePackages: NotRequired[dict[str, list[str | PatchVersion] | None] | list[PatchCompatibility] | None]


@with_config(strict=True)
class PatchList(TypedDict):
    patches: list[OnErrorOmit[Patch]]


@with_config(strict=True, extra="allow")
class SourceConfig(TypedDict, total=False):
    enabled: bool
    revancedStars: int


@with_config(strict=True, extra="allow")
class ProjectLists(TypedDict):
    readmeRepos: list[NonEmptyString]
    readmeLinks: list[NonEmptyString]
    newRepos: list[NonEmptyString]
    excludedRepos: list[NonEmptyString]


@with_config(strict=True)
class UpdateState(TypedDict):
    lastDaily: NotRequired[str]
    appHashes: dict[str, dict[str, str]]
    history: dict[str, dict[str, list[str]]]


@with_config(strict=True)
class BundleSource(TypedDict):
    source: NonEmptyString
    repo: NonEmptyString


@with_config(strict=True)
class OfficialCatalog(TypedDict):
    bundles: list[OnErrorOmit[BundleSource]]


@with_config(strict=True)
class JmanSource(TypedDict):
    url: NonEmptyString


@with_config(strict=True, extra="allow")
class RepositoryState(TypedDict, total=False):
    repo: str
    enabled: bool
    revancedStars: int
    main: str | None
    dev: str | None
    image: str | None
    name: str | None
    description: str
    avatarUrl: str
    stars: int
    isArchived: bool


@with_config(strict=True)
class DiscoveredRepository(TypedDict, total=False):
    id: RepositoryId
    etag: str
    enabled: bool
    revancedStars: int


@with_config(strict=True)
class DiscoveryState(TypedDict):
    providers: dict[str, list[NonEmptyString]]
    repositories: dict[Annotated[str, Field(pattern=r"^[^A-Z]+$")], DiscoveredRepository]


@with_config(strict=True)
class RepositoryAvatar(TypedDict, total=False):
    avatar_url: str | None


@with_config(strict=True)
class GitHubRepository(TypedDict):
    id: int
    full_name: NonEmptyString
    stargazers_count: NotRequired[int]
    description: NotRequired[str | None]
    owner: NotRequired[RepositoryAvatar]
    archived: NotRequired[bool]


@with_config(strict=True)
class GitLabRepository(TypedDict):
    path_with_namespace: NonEmptyString
    archived: bool
    id: int
    star_count: NotRequired[int]
    description: NotRequired[str | None]
    avatar_url: NotRequired[str | None]
    namespace: NotRequired[RepositoryAvatar | None]


BUNDLE_MANIFEST = TypeAdapter(BundleManifest)
PATCH_LIST = TypeAdapter(PatchList)
SOURCES = TypeAdapter(dict[str, SourceConfig])
PROJECTS = TypeAdapter(ProjectLists)
OFFICIAL_CATALOG = TypeAdapter(OfficialCatalog)
JMAN_SOURCES = TypeAdapter(list[JmanSource])
REPOSITORIES = TypeAdapter(dict[RepositoryId, RepositoryState])
DISCOVERY = TypeAdapter(DiscoveryState)
UPDATE_STATE = TypeAdapter(UpdateState)
GITHUB_REPOSITORY = TypeAdapter(GitHubRepository)
GITLAB_REPOSITORY = TypeAdapter(GitLabRepository)
