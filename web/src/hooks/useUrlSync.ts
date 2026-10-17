import { useCallback, useEffect, useState } from "react";
import { DEFAULT_TAB } from "@/constants";
import {
	VALID_APP_SORTS,
	VALID_BUNDLE_CATEGORIES,
	VALID_BUNDLE_SORTS,
} from "@/services";

export type NavigationTabType = "apps" | "bundles" | "whats-new";

function parseTabSegments(
	segments: string[],
	validSorts: Set<string>,
	validCategories?: Set<string>,
): { category: string; sort: string } {
	let category = "all";
	let sort = "default";

	for (const segment of segments) {
		if (!segment) continue;
		if (validSorts.has(segment)) {
			sort = segment;
		} else if (validCategories) {
			if (validCategories.has(segment)) {
				category = segment;
			}
		} else if (/^[a-z0-9-]+$/.test(segment)) {
			category = segment;
		}
	}

	return { category, sort };
}

function parseHash(hash: string): {
	tab: NavigationTabType;
	category: string;
	sort: string;
} {
	const cleanHash = hash.replace(/^#/, "").toLowerCase();
	if (!cleanHash) {
		return { tab: DEFAULT_TAB, category: "all", sort: "default" };
	}

	const parts = cleanHash.split(":");
	const firstPart = parts[0];

	if (firstPart === "whats-new") {
		return { tab: "whats-new", category: "all", sort: "default" };
	}

	if (firstPart === "bundles") {
		const { category, sort } = parseTabSegments(
			parts.slice(1),
			VALID_BUNDLE_SORTS,
			VALID_BUNDLE_CATEGORIES,
		);
		return { tab: "bundles", category, sort };
	}

	if (firstPart === "apps") {
		const { category, sort } = parseTabSegments(
			parts.slice(1),
			VALID_APP_SORTS,
		);
		return { tab: "apps", category, sort };
	}

	return { tab: DEFAULT_TAB, category: "all", sort: "default" };
}

function getSortSlug(sortKey: string): string {
	if (!sortKey || sortKey === "default") return "";
	return sortKey;
}

function buildHash(
	tab: NavigationTabType,
	category: string,
	sort: string,
): string {
	if (tab === "whats-new") return "#whats-new";

	const categorySlug = category && category !== "all" ? category : "";
	const sortSlug = getSortSlug(sort);

	return [`#${tab}`, categorySlug, sortSlug].filter(Boolean).join(":");
}

function normalizeUrlHash(
	tab: NavigationTabType,
	category: string,
	sort: string,
) {
	if (typeof window === "undefined") return;

	const expectedCanonicalHash = buildHash(tab, category, sort);
	const currentHash = window.location.hash.toLowerCase();
	const hasEncodingMismatch = /%2F/i.test(window.location.search);

	if (
		currentHash !== expectedCanonicalHash.toLowerCase() ||
		hasEncodingMismatch
	) {
		const targetUrl = new URL(window.location.href);
		targetUrl.hash = expectedCanonicalHash;
		const formattedUrl = targetUrl.toString().replace(/%2F/gi, "/");
		window.history.replaceState(null, "", formattedUrl);
	}
}

function getInitState() {
	if (typeof window === "undefined") {
		return {
			activeTab: DEFAULT_TAB,
			appsCategory: "all",
			bundlesCategory: "all",
			appsSort: "default",
			bundlesSort: "default",
			selectedAppPackageName: null as string | null,
			popupBundleKey: null as string | null,
			popupSearchQuery: "",
		};
	}

	const searchParams = new URLSearchParams(window.location.search);
	const parsedHash = parseHash(window.location.hash);

	const activeTab = parsedHash.tab;
	const appsCategory = parsedHash.tab === "apps" ? parsedHash.category : "all";
	const bundlesCategory =
		parsedHash.tab === "bundles" ? parsedHash.category : "all";

	const appsSort = parsedHash.tab === "apps" ? parsedHash.sort : "default";
	const bundlesSort =
		parsedHash.tab === "bundles" ? parsedHash.sort : "default";

	const selectedAppPackageName = searchParams.get("app");

	const githubRepo = searchParams.get("github");
	const gitlabRepo = searchParams.get("gitlab");
	const isTestBundleUrl =
		searchParams.has("test-bundle") ||
		window.location.hash.includes("test-bundle");

	let popupBundleKey: string | null = null;
	if (!isTestBundleUrl) {
		if (githubRepo) {
			popupBundleKey = `github:${githubRepo}`;
		} else if (gitlabRepo) {
			popupBundleKey = `gitlab:${gitlabRepo}`;
		} else {
			popupBundleKey = null;
		}
	}

	const popupSearchQuery = searchParams.get("patch") || "";

	return {
		activeTab,
		appsCategory,
		bundlesCategory,
		appsSort,
		bundlesSort,
		selectedAppPackageName,
		popupBundleKey,
		popupSearchQuery,
	};
}

export function useUrlSync() {
	const [initState] = useState(getInitState);

	const [activeTab, setActiveTab] = useState<NavigationTabType>(
		initState.activeTab,
	);
	const [appsCategory, setAppsCategory] = useState(initState.appsCategory);
	const [bundlesCategory, setBundlesCategory] = useState(
		initState.bundlesCategory,
	);
	const [appsSort, setAppsSort] = useState(initState.appsSort);
	const [bundlesSort, setBundlesSort] = useState(initState.bundlesSort);
	const [selectedAppPackageName, setSelectedAppPackageName] = useState<
		string | null
	>(initState.selectedAppPackageName);
	const [popupBundleKey, setPopupBundleKey] = useState<string | null>(
		initState.popupBundleKey,
	);
	const [popupSearchQuery, setPopupSearchQuery] = useState(
		initState.popupSearchQuery,
	);

	const selectedCategory =
		activeTab === "bundles" ? bundlesCategory : appsCategory;
	const sortOrder = activeTab === "bundles" ? bundlesSort : appsSort;

	const syncFromUrl = useCallback(() => {
		if (typeof window === "undefined") return;

		const nextState = getInitState();

		setActiveTab(nextState.activeTab);
		setAppsCategory(nextState.appsCategory);
		setBundlesCategory(nextState.bundlesCategory);
		setAppsSort(nextState.appsSort);
		setBundlesSort(nextState.bundlesSort);
		setSelectedAppPackageName(nextState.selectedAppPackageName);
		setPopupBundleKey(nextState.popupBundleKey);
		setPopupSearchQuery(nextState.popupSearchQuery);

		const nextCategory =
			nextState.activeTab === "bundles"
				? nextState.bundlesCategory
				: nextState.appsCategory;
		const nextSort =
			nextState.activeTab === "bundles"
				? nextState.bundlesSort
				: nextState.appsSort;

		normalizeUrlHash(nextState.activeTab, nextCategory, nextSort);
	}, []);

	useEffect(() => {
		const initCategory =
			initState.activeTab === "bundles"
				? initState.bundlesCategory
				: initState.appsCategory;
		const initSort =
			initState.activeTab === "bundles"
				? initState.bundlesSort
				: initState.appsSort;

		normalizeUrlHash(initState.activeTab, initCategory, initSort);

		window.addEventListener("popstate", syncFromUrl);
		window.addEventListener("hashchange", syncFromUrl);
		return () => {
			window.removeEventListener("popstate", syncFromUrl);
			window.removeEventListener("hashchange", syncFromUrl);
		};
	}, [initState, syncFromUrl]);

	const updateUrl = useCallback(
		(urlUpdates: {
			app?: string | null;
			bundle?: string | null;
			search?: string;
			tab?: NavigationTabType;
			category?: string;
			sort?: string;
		}) => {
			if (typeof window === "undefined") return;

			const targetUrl = new URL(window.location.href);

			if (urlUpdates.app !== undefined) {
				if (urlUpdates.app) {
					targetUrl.searchParams.set("app", urlUpdates.app);
				} else {
					targetUrl.searchParams.delete("app");
				}
			}

			if (urlUpdates.bundle !== undefined) {
				if (urlUpdates.bundle) {
					const [source, repo] = urlUpdates.bundle.split(":");
					if (source && repo) {
						targetUrl.searchParams.set(source, repo);
					}
				} else {
					targetUrl.searchParams.delete("github");
					targetUrl.searchParams.delete("gitlab");
				}
			}

			if (urlUpdates.search !== undefined) {
				if (urlUpdates.search) {
					targetUrl.searchParams.set("patch", urlUpdates.search);
				} else {
					targetUrl.searchParams.delete("patch");
				}
			}

			let nextTab = activeTab;
			let nextCategory =
				activeTab === "bundles" ? bundlesCategory : appsCategory;
			let nextSort = activeTab === "bundles" ? bundlesSort : appsSort;

			if (urlUpdates.tab !== undefined) {
				nextTab = urlUpdates.tab;
				setActiveTab(urlUpdates.tab);
				nextCategory =
					urlUpdates.tab === "bundles" ? bundlesCategory : appsCategory;
				nextSort = urlUpdates.tab === "bundles" ? bundlesSort : appsSort;
			}

			if (urlUpdates.category !== undefined) {
				nextCategory = urlUpdates.category;
				if (nextTab === "apps") {
					setAppsCategory(urlUpdates.category);
				} else if (nextTab === "bundles") {
					setBundlesCategory(urlUpdates.category);
				}
			}

			if (urlUpdates.sort !== undefined) {
				nextSort = urlUpdates.sort;
				if (nextTab === "apps") {
					setAppsSort(urlUpdates.sort);
				} else if (nextTab === "bundles") {
					setBundlesSort(urlUpdates.sort);
				}
			}

			targetUrl.hash = buildHash(nextTab, nextCategory, nextSort);

			const formattedUrlString = targetUrl.toString().replace(/%2F/gi, "/");
			window.history.pushState(null, "", formattedUrlString);
			syncFromUrl();
		},
		[
			syncFromUrl,
			activeTab,
			appsCategory,
			bundlesCategory,
			appsSort,
			bundlesSort,
		],
	);

	return {
		activeTab,
		selectedCategory,
		sortOrder,
		selectedAppPackageName,
		popupBundleKey,
		popupSearchQuery,
		updateUrl,
	};
}
