export interface PatchOption {
  key: string;
  title: string;
  description: string;
}

export interface CompatibilityItem {
  packageName?: string;
  targets?: VersionItem[];
}

export interface PatchItem {
  name: string;
  description: string;
  default?: boolean;
  options?: PatchOption[];
  isPreRelease?: boolean;
  firstSeen?: number;
  compatiblePackagesKey?: number;
}

export interface Bundle {
  source: string;
  repo: string;
  name: string;
  repoDescription: string;
  avatarUrl: string;
  stars: number;
  updatedAt: number;
  firstSeen: number;
  hotRank: number | null;
  isPreRelease: boolean;
  isArchived?: boolean;
  appFirstSeen: Record<string, number>;
  appUpdates?: Record<string, number>;
  patches: PatchItem[];

  key: string;
  patchCount: number;
  appCount: number;
  repoUrl: string;
  deepLink: string;
  changelogUrl: string;
  searchableText: string;
  isUnofficial: boolean;
}

export interface VersionItem {
  version: string;
  isExperimental?: boolean;
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

export interface AppNameMeta {
  name: string;
  iconUrl: string;
  description: string;
  minInstalls: number;
  category: string;
  firstSeen: number;
  updatedAt?: number;
  isPreRelease?: boolean;
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

export interface WhatsNewAppChange {
  patches: string[];
  isNew?: boolean;
  appName?: string;
}

export interface WhatsNewBundleChange {
  apps?: Record<string, WhatsNewAppChange>;
  isNew?: boolean;
}

export interface WhatsNewHistoryItem {
  date: string;
  bundles: Record<string, WhatsNewBundleChange>;
}

export interface ActiveStats {
  bundlesCount: number;
  appsCount: number;
  categoryAppsCount: Record<string, number>;
  categoryBundlesCount: Record<string, number>;
}

export interface ActiveData {
  bundles: Bundle[];
  rows: RowItem[];
  appItems: AppItem[];
  bundleMap: Record<string, Bundle>;
  namesMap: Record<string, AppNameMeta>;
  appPatchesMap: Record<string, RowItem[]>;
  bundlePatchesMap: Record<string, RowItem[]>;
  stats: ActiveStats;
}
