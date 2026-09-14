import { AppItem, RowItem, Bundle, ActiveData } from "@/types/data";
import { simplifyString, getAppMeta, AppMeta, isNew } from "@/utils";
import {
  CATEGORY_UNIVERSAL,
  CATEGORY_LABEL_UNIVERSAL,
  PACKAGE_UNIVERSAL,
  BUNDLE_CATEGORY_OPTIONS,
} from "@/constants";

function parseSearchQuery(query: string): string[] {
  if (!query) return [];
  const trimmed = query.trim();
  if (!trimmed) return [];
  return trimmed.split(/\s+/).map(simplifyString).filter(Boolean);
}

export function compareUniversalApp(
  appItemA: { packageName?: string },
  appItemB: { packageName?: string },
): number {
  if (
    appItemA.packageName &&
    appItemB.packageName &&
    (appItemA.packageName === PACKAGE_UNIVERSAL) !==
      (appItemB.packageName === PACKAGE_UNIVERSAL)
  ) {
    return appItemA.packageName === PACKAGE_UNIVERSAL ? 1 : -1;
  }
  return 0;
}

export function compareAppFallback(
  appItemA: { patchCount?: number; appName: string; packageName?: string },
  appItemB: { patchCount?: number; appName: string; packageName?: string },
): number {
  return (
    (appItemB.patchCount ?? 0) - (appItemA.patchCount ?? 0) ||
    appItemA.appName.localeCompare(appItemB.appName) ||
    (appItemA.packageName || "").localeCompare(appItemB.packageName || "")
  );
}

export function compareDefaultApp(
  appItemA: {
    packageName?: string;
    minInstalls: number;
    appName: string;
    patchCount?: number;
  },
  appItemB: {
    packageName?: string;
    minInstalls: number;
    appName: string;
    patchCount?: number;
  },
): number {
  return (
    compareUniversalApp(appItemA, appItemB) ||
    appItemB.minInstalls - appItemA.minInstalls ||
    compareAppFallback(appItemA, appItemB)
  );
}

export function compareBundleFallback(
  bundleItemA: Bundle,
  bundleItemB: Bundle,
): number {
  return (
    bundleItemB.stars - bundleItemA.stars ||
    bundleItemB.updatedAt - bundleItemA.updatedAt ||
    bundleItemA.name.localeCompare(bundleItemB.name) ||
    bundleItemA.key.localeCompare(bundleItemB.key)
  );
}

export function compareDefaultBundle(
  bundleItemA: Bundle,
  bundleItemB: Bundle,
): number {
  const rankA = bundleItemA.hotRank;
  const rankB = bundleItemB.hotRank;

  if (rankA !== null && rankB !== null) {
    return rankA - rankB || compareBundleFallback(bundleItemA, bundleItemB);
  }
  if (rankA !== null) return -1;
  if (rankB !== null) return 1;

  return compareBundleFallback(bundleItemA, bundleItemB);
}

export function comparePatches(patchA: RowItem, patchB: RowItem): number {
  const isNewA = isNew(patchA.firstSeen);
  const isNewB = isNew(patchB.firstSeen);
  if (isNewA !== isNewB) {
    return isNewA ? -1 : 1;
  }
  if (isNewA && isNewB) {
    const diffFirstSeen = (patchB.firstSeen || 0) - (patchA.firstSeen || 0);
    if (diffFirstSeen !== 0) return diffFirstSeen;
  }
  return 0;
}

const BUNDLE_SORT_KEY_MAP: Record<string, (bundle: Bundle) => number> = {
  new: (bundle) => -bundle.firstSeen,
  updated: (bundle) => -bundle.updatedAt,
  stars: (bundle) => -bundle.stars,
  apps: (bundle) => -bundle.appCount,
  patches: (bundle) => -bundle.patchCount,
};

const APP_SORT_KEY_MAP: Record<string, (app: AppItem) => number> = {
  new: (app) => -app.firstSeen,
  updated: (app) => -app.updatedAt,
  patches: (app) => -app.patchCount,
};

export const VALID_APP_SORTS = new Set([
  ...Object.keys(APP_SORT_KEY_MAP),
  "alpha",
]);

export const VALID_BUNDLE_SORTS = new Set([
  ...Object.keys(BUNDLE_SORT_KEY_MAP),
  "alpha",
]);

export const VALID_BUNDLE_CATEGORIES = new Set(
  BUNDLE_CATEGORY_OPTIONS.map((categoryOption) => categoryOption.key),
);

export function getAppItems(
  appItems: AppItem[],
  searchQuery = "",
  sortOrder = "default",
  categoryFilter = "all",
): AppItem[] {
  let appList: AppItem[];

  const queryWords = parseSearchQuery(searchQuery);
  const hasCategoryFilter = categoryFilter !== "all";
  const hasSearch = queryWords.length > 0;

  if (hasCategoryFilter || hasSearch) {
    appList = appItems.filter((appItem) => {
      if (hasCategoryFilter && appItem.categorySlug !== categoryFilter) {
        return false;
      }
      if (hasSearch) {
        for (let i = 0; i < queryWords.length; i++) {
          if (!appItem.searchableText.includes(queryWords[i])) return false;
        }
      }
      return true;
    });
  } else {
    appList = [...appItems];
  }

  const appSortKeySelector = APP_SORT_KEY_MAP[sortOrder];
  appList.sort((appItemA, appItemB) => {
    const universalDiff = compareUniversalApp(appItemA, appItemB);
    if (universalDiff !== 0) return universalDiff;

    if (appSortKeySelector) {
      return (
        appSortKeySelector(appItemA) - appSortKeySelector(appItemB) ||
        compareAppFallback(appItemA, appItemB)
      );
    }
    if (sortOrder === "alpha") {
      return (
        appItemA.appName.localeCompare(appItemB.appName) ||
        compareAppFallback(appItemA, appItemB)
      );
    }
    return compareDefaultApp(appItemA, appItemB);
  });

  return appList;
}

export function getAvailableCategories(
  appItems: AppItem[],
): { key: string; label: string }[] {
  const categoriesMap = new Map<string, string>();
  let hasNotOnGooglePlay = false;

  for (const appItem of appItems) {
    if (appItem.categorySlug === CATEGORY_UNIVERSAL) {
      hasNotOnGooglePlay = true;
    } else if (appItem.category) {
      categoriesMap.set(appItem.categorySlug, appItem.category);
    }
  }

  const sortedCategories = Array.from(categoriesMap.entries())
    .sort(([, labelA], [, labelB]) => labelA.localeCompare(labelB))
    .map(([key, label]) => ({ key, label }));

  return [
    { key: "all", label: "All categories" },
    ...(hasNotOnGooglePlay
      ? [{ key: CATEGORY_UNIVERSAL, label: CATEGORY_LABEL_UNIVERSAL }]
      : []),
    ...sortedCategories,
  ];
}

export function getBundleItems(
  bundles: Bundle[],
  searchQuery = "",
  sortOrder = "default",
  categoryFilter = "all",
): Bundle[] {
  let bundleList: Bundle[];

  const queryWords = parseSearchQuery(searchQuery);
  const isOfficialFilter = categoryFilter === "official";
  const isUnofficialFilter = categoryFilter === "unofficial";
  const hasCategoryFilter = isOfficialFilter || isUnofficialFilter;
  const hasSearch = queryWords.length > 0;

  if (hasCategoryFilter || hasSearch) {
    bundleList = bundles.filter((bundleItem) => {
      if (isOfficialFilter && bundleItem.isUnofficial) return false;
      if (isUnofficialFilter && !bundleItem.isUnofficial) return false;

      if (hasSearch) {
        for (let i = 0; i < queryWords.length; i++) {
          if (!bundleItem.searchableText.includes(queryWords[i])) return false;
        }
      }
      return true;
    });
  } else {
    bundleList = [...bundles];
  }

  const bundleSortKeySelector = BUNDLE_SORT_KEY_MAP[sortOrder];
  if (bundleSortKeySelector) {
    bundleList.sort(
      (bundleA, bundleB) =>
        bundleSortKeySelector(bundleA) - bundleSortKeySelector(bundleB) ||
        compareBundleFallback(bundleA, bundleB),
    );
  } else if (sortOrder === "alpha") {
    bundleList.sort(
      (bundleA, bundleB) =>
        bundleA.name.localeCompare(bundleB.name) ||
        compareBundleFallback(bundleA, bundleB),
    );
  } else {
    bundleList.sort(compareDefaultBundle);
  }

  return bundleList;
}

export interface BundleGroupData {
  bundleKey: string;
  bundleMeta: Bundle;
  patches: RowItem[];
  totalPatchCount: number;
}

export function getAppBundleGroups(
  activeData: ActiveData,
  packageName: string,
  searchQuery: string,
  sortByUpdated: boolean = false,
): BundleGroupData[] {
  const rawPatches = activeData.appPatchesMap[packageName] || [];
  if (rawPatches.length === 0) return [];

  const rawBundlesMap = new Map<
    string,
    { patches: RowItem[]; bundleMeta: Bundle }
  >();
  for (const patchItem of rawPatches) {
    const bundleKey = patchItem.bundleKey.toLowerCase();
    let group = rawBundlesMap.get(bundleKey);
    if (!group) {
      const bundleMeta = activeData.bundleMap[bundleKey];
      if (!bundleMeta) continue;
      group = { patches: [], bundleMeta };
      rawBundlesMap.set(bundleKey, group);
    }
    group.patches.push(patchItem);
  }

  const queryWords = parseSearchQuery(searchQuery);
  const result: BundleGroupData[] = [];

  for (const [bundleKey, group] of rawBundlesMap.entries()) {
    const totalPatchCount = group.patches.length;
    let filteredPatches = group.patches;

    if (queryWords.length > 0) {
      const bundleNameClean = simplifyString(group.bundleMeta.name);
      const bundleRepoClean = simplifyString(group.bundleMeta.repo);
      const isBundleMatched = queryWords.every(
        (word) =>
          bundleNameClean.includes(word) || bundleRepoClean.includes(word),
      );

      if (!isBundleMatched) {
        filteredPatches = group.patches.filter((patchItem) =>
          queryWords.every((word) =>
            patchItem.searchPatchesText.includes(word),
          ),
        );
      }
    }

    if (filteredPatches.length > 0) {
      result.push({
        bundleKey,
        bundleMeta: group.bundleMeta,
        patches: filteredPatches.slice().sort(comparePatches),
        totalPatchCount,
      });
    }
  }

  return result.sort((groupA, groupB) => {
    if (sortByUpdated) {
      const updatedA =
        groupA.bundleMeta.appUpdates?.[packageName] ??
        groupA.bundleMeta.updatedAt;
      const updatedB =
        groupB.bundleMeta.appUpdates?.[packageName] ??
        groupB.bundleMeta.updatedAt;
      const diffUpdated = updatedB - updatedA;
      if (diffUpdated !== 0) return diffUpdated;
    }
    return compareDefaultBundle(groupA.bundleMeta, groupB.bundleMeta);
  });
}

export interface AppGroupData {
  packageName: string;
  appMeta: AppMeta;
  patches: RowItem[];
  totalPatchCount: number;
}

export function groupPatchesByApp(
  patches: RowItem[],
  activeData: ActiveData,
  searchQuery: string = "",
  parentBundle?: Bundle,
): AppGroupData[] {
  if (!patches || patches.length === 0) return [];

  const rawAppsMap = new Map<
    string,
    { patches: RowItem[]; appMeta: AppGroupData["appMeta"] }
  >();
  for (const patchItem of patches) {
    const packageName = patchItem.packageName;
    let group = rawAppsMap.get(packageName);
    if (!group) {
      group = {
        patches: [],
        appMeta: getAppMeta(packageName, activeData.namesMap),
      };
      rawAppsMap.set(packageName, group);
    }
    group.patches.push(patchItem);
  }

  const queryWords = parseSearchQuery(searchQuery);
  const result: AppGroupData[] = [];

  for (const [packageName, group] of rawAppsMap.entries()) {
    const totalPatchCount = group.patches.length;
    let filteredPatches = group.patches;

    if (queryWords.length > 0) {
      const appNameClean = simplifyString(group.appMeta.appName);
      const packageNameClean = simplifyString(packageName);
      const isAppMatched = queryWords.every(
        (word) =>
          appNameClean.includes(word) || packageNameClean.includes(word),
      );

      if (!isAppMatched) {
        filteredPatches = group.patches.filter((patchItem) =>
          queryWords.every((word) =>
            patchItem.searchPatchesText.includes(word),
          ),
        );
      }
    }

    if (filteredPatches.length > 0) {
      result.push({
        packageName,
        appMeta: group.appMeta,
        patches: filteredPatches.slice().sort(comparePatches),
        totalPatchCount,
      });
    }
  }

  return result.sort((groupA, groupB) => {
    if (parentBundle) {
      const firstSeenA =
        parentBundle.appFirstSeen?.[groupA.packageName] ??
        groupA.appMeta.firstSeen;
      const firstSeenB =
        parentBundle.appFirstSeen?.[groupB.packageName] ??
        groupB.appMeta.firstSeen;
      if (firstSeenA !== firstSeenB) {
        return firstSeenB - firstSeenA;
      }
    }
    return compareDefaultApp(
      { ...groupA.appMeta, patchCount: groupA.totalPatchCount },
      { ...groupB.appMeta, patchCount: groupB.totalPatchCount },
    );
  });
}

export function getBundleAppGroups(
  activeData: ActiveData,
  bundleKey: string,
  searchQuery: string,
  sortByNewest: boolean = false,
): AppGroupData[] {
  const bundleKeyLower = bundleKey.toLowerCase();
  const filteredPatches = activeData.bundlePatchesMap[bundleKeyLower] || [];
  const parentBundle = sortByNewest
    ? activeData.bundleMap[bundleKeyLower]
    : undefined;
  return groupPatchesByApp(
    filteredPatches,
    activeData,
    searchQuery,
    parentBundle,
  );
}
