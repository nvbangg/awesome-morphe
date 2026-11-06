import { PACKAGE_UNIVERSAL } from "@/constants";
import { simplifyString } from "@/lib/stringUtils";
import { buildBundleUrls, extractVersions, getAppMeta } from "./helpers";
import type { CatalogArtifact } from "./schema";
import type {
	ActiveData,
	ActiveStats,
	AppItem,
	Bundle,
	CompatibilityItem,
	RowItem,
} from "./types";

const UNIVERSAL_TARGET: CompatibilityItem[] = [
	{ packageName: PACKAGE_UNIVERSAL, targets: [] },
];

export function buildCatalog(sourcesData: CatalogArtifact): ActiveData {
	const jsonBundles = sourcesData.bundles;
	const appNamesMap = sourcesData.store;
	const compatibilitiesList = sourcesData.compatibilities;

	const bundleList: Bundle[] = [];
	const rows: RowItem[] = [];

	for (const jsonBundle of jsonBundles) {
		const bundleKey = `${jsonBundle.source}:${jsonBundle.repo}`;
		const calculatedUrls = buildBundleUrls(
			jsonBundle.source,
			jsonBundle.repo,
			jsonBundle.isPreRelease,
		);

		const isOfficial = !!jsonBundle.isOfficial;
		const hotRank = jsonBundle.hotRank;

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
			isOfficial,
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
			isUnofficial: !isOfficial,
			isArchived: !!jsonBundle.isArchived,
		};

		bundleList.push(bundleItem);

		const patchRows = bundleItem.patches.flatMap((patchItem, patchIndex) => {
			const patchId = `${bundleKey}:${patchIndex}`;
			const compatiblePackages =
				patchItem.compatiblePackagesKey !== undefined
					? compatibilitiesList[patchItem.compatiblePackagesKey]
					: undefined;

			let packageTargetRows: CompatibilityItem[] = (compatiblePackages ?? [])
				.filter((item) => item.packageName)
				.map((item) => ({
					packageName: item.packageName,
					targets: extractVersions(item.targets),
				}));
			if (packageTargetRows.length === 0) {
				packageTargetRows = UNIVERSAL_TARGET;
			}

			const searchParts = [patchItem.name, patchItem.description];
			for (const patchOption of patchItem.options ?? []) {
				searchParts.push(
					patchOption.title,
					patchOption.key,
					patchOption.description,
				);
			}
			const searchPatchesText = simplifyString(
				searchParts.filter(Boolean).join(" "),
			);

			return packageTargetRows.map((targetPackage, targetIndex) => ({
				id: `${patchId}:${targetIndex}`,
				bundleKey,
				patchName: patchItem.name,
				patchDesc: patchItem.description,
				packageName: targetPackage.packageName,
				isPatchPreRelease:
					Boolean(jsonBundle.isPreRelease) || Boolean(patchItem.isPreRelease),
				versions: targetPackage.targets ?? [],
				searchPatchesText,
				options: patchItem.options,
				default: patchItem.default,
				firstSeen: patchItem.firstSeen,
			}));
		});

		rows.push(...patchRows);
	}

	const appPatchesMap: Record<string, RowItem[]> = {};
	const bundlePatchesMap: Record<string, RowItem[]> = {};

	for (const rowItem of rows) {
		appPatchesMap[rowItem.packageName] ??= [];
		appPatchesMap[rowItem.packageName].push(rowItem);
		const bundleKey = rowItem.bundleKey.toLowerCase();
		bundlePatchesMap[bundleKey] ??= [];
		bundlePatchesMap[bundleKey].push(rowItem);
	}

	const bundleMap: Record<string, Bundle> = {};
	for (const bundle of bundleList) {
		bundleMap[bundle.key.toLowerCase()] = bundle;
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
		appItems,
		bundleMap,
		namesMap: appNamesMap,
		appPatchesMap,
		bundlePatchesMap,
		stats,
	};
}
