import {
  ActiveData,
  Bundle,
  RowItem,
  AppItem,
  CompatibilityItem,
  WhatsNewHistoryItem,
  ActiveStats,
  AppNameMeta,
} from "@/types/data";
import {
  buildBundleUrls,
  getAppMeta,
  extractVersions,
  simplifyString,
} from "@/utils";

import { PACKAGE_UNIVERSAL } from "@/constants";

const universalDefaultTarget: CompatibilityItem[] = [
  { packageName: PACKAGE_UNIVERSAL, targets: [] },
];

const jsonCache = new Map<string, Promise<unknown>>();
let activeDataPromise: Promise<ActiveData> | null = null;

export function fetchJson<T = unknown>(
  url: string | URL,
  defaultFallbackData?: T,
): Promise<T> {
  const cacheKey = url.toString();
  let fetchPromise = jsonCache.get(cacheKey) as Promise<T> | undefined;

  if (!fetchPromise) {
    fetchPromise = (async () => {
      try {
        const response = await fetch(url);
        if (!response.ok) {
          throw new Error(`Failed to load ${url}: ${response.status}`);
        }
        return (await response.json()) as T;
      } catch (error) {
        jsonCache.delete(cacheKey);
        if (defaultFallbackData !== undefined) return defaultFallbackData;
        throw error;
      }
    })();
    jsonCache.set(cacheKey, fetchPromise);
  }

  return fetchPromise;
}

export function fetchWhatsNewHistory(): Promise<WhatsNewHistoryItem[]> {
  return fetchJson<WhatsNewHistoryItem[]>("whats-new.json", []);
}

interface BundlesResponseData {
  bundles: Bundle[];
  compatibilities: CompatibilityItem[][];
  store: Record<string, AppNameMeta>;
}

export function loadInitData(): Promise<ActiveData> {
  if (activeDataPromise) {
    return activeDataPromise;
  }

  activeDataPromise = (async () => {
    const sourcesData = await fetchJson<BundlesResponseData>("bundles.json", {
      bundles: [],
      compatibilities: [],
      store: {},
    });
    const jsonBundles = sourcesData.bundles;
    const appNamesMap = sourcesData.store;
    const compatibilitiesList = sourcesData.compatibilities;

    const bundleList: Bundle[] = [];
    const rows: RowItem[] = [];

    for (const jsonBundle of jsonBundles) {
      if (!jsonBundle.patches) continue;

      const bundleKey = `${jsonBundle.source}:${jsonBundle.repo}`;
      const calculatedUrls = buildBundleUrls(
        jsonBundle.source,
        jsonBundle.repo,
        jsonBundle.isPreRelease,
      );

      const hotRank =
        jsonBundle.hotRank !== undefined && jsonBundle.hotRank !== null
          ? jsonBundle.hotRank
          : null;

      const bundleItem: Bundle = {
        source: jsonBundle.source,
        repo: jsonBundle.repo,
        name: jsonBundle.name,
        repoDescription: jsonBundle.repoDescription,
        avatarUrl: jsonBundle.avatarUrl,
        stars: jsonBundle.stars,
        updatedAt: jsonBundle.updatedAt,
        firstSeen: jsonBundle.firstSeen,
        hotRank,
        isPreRelease: !!jsonBundle.isPreRelease,
        appFirstSeen: jsonBundle.appFirstSeen,
        appUpdates: jsonBundle.appUpdates,
        patches: jsonBundle.patches,

        key: bundleKey,
        patchCount: jsonBundle.patches.length,
        appCount: Object.keys(jsonBundle.appFirstSeen).length,
        repoUrl: calculatedUrls.repoUrl,
        deepLink: calculatedUrls.deepLink,
        changelogUrl: calculatedUrls.changelogUrl,
        searchableText: simplifyString(
          `${jsonBundle.name} ${jsonBundle.source} ${jsonBundle.repo}`,
        ),
        isUnofficial: hotRank === null,
        isArchived: !!jsonBundle.isArchived,
      };

      bundleList.push(bundleItem);

      const patchRows = bundleItem.patches.flatMap((patchItem, patchIndex) => {
        const patchId = `${bundleKey}:${patchIndex}`;
        const compatiblePackages =
          patchItem.compatiblePackagesKey !== undefined
            ? compatibilitiesList[patchItem.compatiblePackagesKey]
            : undefined;

        let packageTargetRows: CompatibilityItem[] = universalDefaultTarget;
        if (Array.isArray(compatiblePackages)) {
          const mappedTargetRows: CompatibilityItem[] = [];
          for (const compatibilityItem of compatiblePackages) {
            if (compatibilityItem?.packageName) {
              mappedTargetRows.push({
                packageName: compatibilityItem.packageName,
                targets: extractVersions(compatibilityItem.targets),
              });
            }
          }
          if (mappedTargetRows.length > 0) {
            packageTargetRows = mappedTargetRows;
          }
        }

        const searchParts = [patchItem.name, patchItem.description];
        if (Array.isArray(patchItem.options)) {
          for (const patchOption of patchItem.options) {
            searchParts.push(
              patchOption.title,
              patchOption.key,
              patchOption.description,
            );
          }
        }
        const searchPatchesText = simplifyString(
          searchParts.filter(Boolean).join(" "),
        );

        return packageTargetRows.map((targetPackage, targetIndex) => ({
          id: `${patchId}:${targetIndex}`,
          bundleKey,
          patchName: patchItem.name,
          patchDesc: patchItem.description,
          packageName: targetPackage.packageName ?? PACKAGE_UNIVERSAL,
          isPatchPreRelease:
            Boolean(jsonBundle.isPreRelease) || Boolean(patchItem.isPreRelease),
          versions: targetPackage.targets ?? [],
          searchPatchesText,
          options: patchItem.options,
          default: patchItem.default,
        }));
      });

      rows.push(...patchRows);
    }

    const appPatchesMap: Record<string, RowItem[]> = {};
    const bundlePatchesMap: Record<string, RowItem[]> = {};

    for (const rowItem of rows) {
      (appPatchesMap[rowItem.packageName] ??= []).push(rowItem);
      (bundlePatchesMap[rowItem.bundleKey.toLowerCase()] ??= []).push(rowItem);
    }

    const bundleMap: Record<string, Bundle> = {};
    for (const bundle of bundleList) {
      bundleMap[bundle.key.toLowerCase()] = bundle;
      bundleMap[bundle.repo.toLowerCase()] = bundle;
    }

    const appMap = new Map<string, AppItem>();
    for (const rowItem of rows) {
      const packageName = rowItem.packageName;
      const bundleItem = bundleMap[rowItem.bundleKey.toLowerCase()];
      const bundleAppUpdate = bundleItem?.appUpdates?.[packageName] || 0;
      const existingApp = appMap.get(packageName);
      if (!existingApp) {
        const appMeta = getAppMeta(packageName, appNamesMap);
        const searchableText = simplifyString(
          `${appMeta.appName} ${packageName} ${appMeta.description}`,
        );
        appMap.set(packageName, {
          packageName,
          appName: appMeta.appName,
          appIcon: appMeta.appIcon,
          description: appMeta.description,
          minInstalls: appMeta.minInstalls,
          category: appMeta.category,
          firstSeen: appMeta.firstSeen,
          updatedAt: Math.max(appMeta.updatedAt, bundleAppUpdate),
          patchCount: 1,
          categorySlug: appMeta.categorySlug,
          searchableText,
          isPreRelease: appMeta.isPreRelease,
        });
      } else {
        existingApp.patchCount += 1;
        if (bundleAppUpdate > existingApp.updatedAt) {
          existingApp.updatedAt = bundleAppUpdate;
        }
      }
    }
    const appItems = Array.from(appMap.values());

    const categoryAppsCount: Record<string, number> = {};
    for (const appItem of appItems) {
      categoryAppsCount[appItem.categorySlug] =
        (categoryAppsCount[appItem.categorySlug] || 0) + 1;
    }

    const officialBundlesCount = bundleList.filter(
      (bundle) => !bundle.isUnofficial,
    ).length;
    const categoryBundlesCount: Record<string, number> = {
      official: officialBundlesCount,
      unofficial: bundleList.length - officialBundlesCount,
    };

    const stats: ActiveStats = {
      bundlesCount: bundleList.length,
      appsCount: appItems.reduce(
        (count, appItem) =>
          count + (appItem.packageName !== PACKAGE_UNIVERSAL ? 1 : 0),
        0,
      ),
      categoryAppsCount,
      categoryBundlesCount,
    };

    return {
      bundles: bundleList,
      rows,
      appItems,
      bundleMap,
      namesMap: appNamesMap,
      appPatchesMap,
      bundlePatchesMap,
      stats,
    };
  })();

  return activeDataPromise;
}
