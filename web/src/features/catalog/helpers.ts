import { CATEGORY_LABEL_UNIVERSAL } from "@/constants";
import type {
	AppNameMeta,
	Bundle,
	RowItem,
	VersionItem,
} from "@/features/catalog/types";
import { slugifyCategory } from "@/lib/stringUtils";

export function isAllPatchesPreRelease(patches: RowItem[]): boolean {
	return (
		patches.length > 0 &&
		patches.every((patchItem) => patchItem.isPatchPreRelease)
	);
}

export function extractVersions(
	rawVersions: { version: string | null; isExperimental?: boolean }[] = [],
): VersionItem[] {
	return rawVersions
		.flatMap(({ version, isExperimental }) =>
			version
				? [
						{
							version,
							isExperimental: !!isExperimental,
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
	source: Bundle["source"],
	repo: string,
	isPreRelease: boolean | undefined,
): { repoUrl: string; deepLink: string; changelogUrl: string } {
	if (!repo) return { repoUrl: "", deepLink: "", changelogUrl: "" };

	const repoUrl = `https://${source}.com/${repo}`;
	const deepLinkRepo = isPreRelease
		? source === "gitlab"
			? `${repo}/-/tree/dev`
			: `${repo}/tree/dev`
		: repo;
	return {
		repoUrl,
		deepLink: `https://morphe.software/add-source?${source}=${deepLinkRepo}`,
		changelogUrl:
			source === "gitlab" ? `${repoUrl}/-/releases` : `${repoUrl}/releases`,
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
		updatedAt: appMeta?.updatedAt || 0,
		isPreRelease: Boolean(appMeta?.isPreRelease),
	};
}

export type AppMeta = ReturnType<typeof getAppMeta>;
