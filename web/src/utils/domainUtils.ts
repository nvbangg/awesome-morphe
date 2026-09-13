import { VersionItem, AppNameMeta, Bundle, RowItem } from "@/types/data";
import { CATEGORY_LABEL_UNIVERSAL } from "@/constants";
import { slugifyCategory } from "./stringUtils";

export function isAllPatchesPreRelease(patches: RowItem[]): boolean {
  return (
    patches.length > 0 &&
    patches.every((patchItem) => patchItem.isPatchPreRelease)
  );
}

export function extractVersions(rawVersionsValue: unknown): VersionItem[] {
  if (!Array.isArray(rawVersionsValue)) return [];
  return (rawVersionsValue as VersionItem[])
    .flatMap((item) =>
      item?.version
        ? [
            {
              version: String(item.version),
              isExperimental: !!item.isExperimental,
            },
          ]
        : [],
    )
    .sort((versionA, versionB) =>
      versionB.version.localeCompare(versionA.version, undefined, {
        numeric: true,
        sensitivity: "base",
      }),
    );
}

export function buildBundleUrls(
  source: string | undefined,
  repo: string | undefined,
  isPreRelease: boolean | undefined,
): { repoUrl: string; deepLink: string; changelogUrl: string } {
  if (!repo) return { repoUrl: "", deepLink: "", changelogUrl: "" };

  const repoSource = source || "github";
  const repoUrl = `https://${repoSource}.com/${repo}`;
  const deepLinkRepo = isPreRelease
    ? repoSource === "gitlab"
      ? `${repo}/-/tree/dev`
      : `${repo}/tree/dev`
    : repo;
  return {
    repoUrl,
    deepLink: `https://morphe.software/add-source?${repoSource}=${deepLinkRepo}`,
    changelogUrl:
      repoSource === "gitlab" ? `${repoUrl}/-/releases` : `${repoUrl}/releases`,
  };
}

export function getAppMeta(
  packageName: string,
  appNamesMap: Record<string, AppNameMeta>,
) {
  const appMeta = appNamesMap[packageName];
  const category = appMeta?.category || CATEGORY_LABEL_UNIVERSAL;
  return {
    packageName,
    appName: appMeta?.name || packageName,
    appIcon: appMeta?.iconUrl || "",
    description: appMeta?.description || "",
    minInstalls: appMeta?.minInstalls || 0,
    category,
    categorySlug: slugifyCategory(category),
    firstSeen: appMeta?.firstSeen || 0,
    isPreRelease: Boolean(appMeta?.isPreRelease),
  };
}

export type AppMeta = ReturnType<typeof getAppMeta>;

export type BundleMeta = Bundle;

export function getBundleMeta(
  bundleKey: string,
  bundleMap: Record<string, Bundle>,
): Bundle | null {
  return bundleMap[bundleKey.toLowerCase()] || null;
}
