import type { z } from "zod";
import type {
	appMetadataSchema,
	bundleSchema,
	compatibilitySchema,
	optionSchema,
	versionSchema,
} from "./schema";
export type PatchOption = z.infer<typeof optionSchema>;
export type CompatibilityItem = Omit<
	z.infer<typeof compatibilitySchema>,
	"targets"
> & { targets?: VersionItem[] };
export type AppNameMeta = z.infer<typeof appMetadataSchema>;
export type VersionItem = z.infer<typeof versionSchema>;
type BundleArtifact = z.infer<typeof bundleSchema>;
export interface Bundle extends BundleArtifact {
	isPreRelease: boolean;
	key: string;
	patchCount: number;
	appCount: number;
	repoUrl: string;
	deepLink: string;
	changelogUrl: string;
	searchableText: string;
	isUnofficial: boolean;
}

export interface RowItem {
	id: string;
	bundleKey: string;
	patchName: string;
	patchDesc: string;
	packageName: string;
	isPatchPreRelease: boolean;
	versions: VersionItem[];
	searchPatchesText: string;
	options?: PatchOption[];
	default?: boolean;
	firstSeen?: number;
}

export interface AppItem {
	packageName: string;
	appName: string;
	appIcon: string;
	description: string;
	minInstalls: number;
	category: string;
	firstSeen: number;
	updatedAt: number;
	patchCount: number;
	categorySlug: string;
	searchableText: string;
	isPreRelease: boolean;
}

export interface ActiveStats {
	bundlesCount: number;
	appsCount: number;
	categoryAppsCount: Record<string, number>;
	categoryBundlesCount: Record<string, number>;
}

export interface ActiveData {
	bundles: Bundle[];
	appItems: AppItem[];
	bundleMap: Record<string, Bundle>;
	namesMap: Record<string, AppNameMeta>;
	appPatchesMap: Record<string, RowItem[]>;
	bundlePatchesMap: Record<string, RowItem[]>;
	stats: ActiveStats;
}
