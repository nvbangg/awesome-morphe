import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PACKAGE_UNIVERSAL } from "../src/constants";
import { buildCatalog } from "../src/features/catalog/model";
import { catalogSchema } from "../src/features/catalog/schema";
import {
	getAppBundleGroups,
	getAppItems,
	getBundleAppGroups,
	getBundleItems,
} from "../src/features/catalog/search";
import {
	ALPHA_PACKAGE,
	BETA_PACKAGE,
	COMMUNITY_KEY,
	CORE_KEY,
	catalog,
	TEST_TIMESTAMP,
} from "./catalog";

describe("catalog rules", () => {
	beforeEach(() => vi.useFakeTimers({ now: TEST_TIMESTAMP }));
	afterEach(() => vi.useRealTimers());

	it("builds consistent app, bundle and universal indexes from validated JSON", () => {
		const data = buildCatalog(catalogSchema.parse(catalog));
		expect(data.stats).toMatchObject({
			appsCount: 2,
			bundlesCount: 2,
			categoryBundlesCount: { official: 1, unofficial: 1 },
		});
		expect(data.appPatchesMap[ALPHA_PACKAGE]).toHaveLength(3);
		expect(data.appPatchesMap[PACKAGE_UNIVERSAL]).toHaveLength(1);
		expect(data.bundlePatchesMap[CORE_KEY.toLowerCase()]).toHaveLength(4);
		expect(
			data.appPatchesMap[ALPHA_PACKAGE].find(
				(patch) => patch.patchName === "Playback options",
			)?.versions,
		).toEqual([{ version: "2.0", isExperimental: false }]);
		expect(
			data.appPatchesMap[ALPHA_PACKAGE].find(
				(patch) => patch.patchName === "Theme controls",
			)?.isPatchPreRelease,
		).toBe(true);
	});

	it("combines accent-insensitive multiword search with category filtering", () => {
		const data = buildCatalog(catalog);
		expect(
			getAppItems(data.appItems, "ĐỌC ngoai", "default", "books-reference").map(
				(app) => app.packageName,
			),
		).toEqual([BETA_PACKAGE]);
		expect(
			getAppItems(
				data.appItems,
				"ĐỌC ngoai",
				"default",
				"video-players-editors",
			),
		).toEqual([]);
		expect(
			getBundleItems(
				data.bundles,
				"GROUP COMMUNITY",
				"default",
				"unofficial",
			).map((bundle) => bundle.key),
		).toEqual([COMMUNITY_KEY]);
	});

	it("preserves default ranking, explicit sort order and universal-last placement", () => {
		const data = buildCatalog(catalog);
		expect(getAppItems(data.appItems).map((app) => app.packageName)).toEqual([
			BETA_PACKAGE,
			ALPHA_PACKAGE,
			PACKAGE_UNIVERSAL,
		]);
		expect(
			getAppItems(data.appItems, "", "patches").map((app) => app.packageName),
		).toEqual([ALPHA_PACKAGE, BETA_PACKAGE, PACKAGE_UNIVERSAL]);
		expect(getBundleItems(data.bundles).map((bundle) => bundle.key)).toEqual([
			CORE_KEY,
			COMMUNITY_KEY,
		]);
		expect(
			getBundleItems(data.bundles, "", "stars").map((bundle) => bundle.key),
		).toEqual([COMMUNITY_KEY, CORE_KEY]);
	});

	it("groups patches in both directions and searches options without losing totals", () => {
		const data = buildCatalog(catalog);
		const groups = getAppBundleGroups(data, ALPHA_PACKAGE, "AUDIO language");
		expect(
			getAppBundleGroups(data, ALPHA_PACKAGE, "")[0].patches.map(
				(patch) => patch.patchName,
			),
		).toEqual(["Playback options", "Remove ads"]);
		expect(groups).toHaveLength(1);
		expect(groups[0]).toMatchObject({
			bundleKey: CORE_KEY.toLowerCase(),
			totalPatchCount: 2,
		});
		expect(groups[0].patches.map((patch) => patch.patchName)).toEqual([
			"Playback options",
		]);
		expect(
			getBundleAppGroups(data, CORE_KEY, "").map((group) => group.packageName),
		).toEqual([BETA_PACKAGE, ALPHA_PACKAGE, PACKAGE_UNIVERSAL]);
	});
});
