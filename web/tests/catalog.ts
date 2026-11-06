import type { CatalogArtifact } from "../src/features/catalog/schema";

export const ALPHA_PACKAGE = "com.example.alpha";
export const BETA_PACKAGE = "com.example.beta";
export const CORE_KEY = "github:Example/core";
export const COMMUNITY_KEY = "gitlab:group/community";
export const TEST_TIMESTAMP = Date.UTC(2026, 0, 15);

export const catalog: CatalogArtifact = {
	bundles: [
		{
			source: "github",
			repo: "Example/core",
			name: "Core patches",
			repoDescription: "Core patch bundle",
			avatarUrl: "",
			stars: 100,
			updatedAt: TEST_TIMESTAMP,
			firstSeen: TEST_TIMESTAMP,
			hotRank: 0,
			isOfficial: true,
			appFirstSeen: {
				[ALPHA_PACKAGE]: TEST_TIMESTAMP,
				[BETA_PACKAGE]: TEST_TIMESTAMP,
			},
			patches: [
				{
					name: "Remove ads",
					description: "Remove advertising",
					compatiblePackagesKey: 0,
				},
				{
					name: "Playback options",
					description: "Configure playback",
					firstSeen: TEST_TIMESTAMP,
					compatiblePackagesKey: 1,
					options: [
						{
							key: "audio",
							title: "Audio language",
							description: "Select language",
						},
					],
				},
				{ name: "Universal patch", description: "Applies to any package" },
			],
		},
		{
			source: "gitlab",
			repo: "group/community",
			name: "Community patches",
			repoDescription: "Community patch bundle",
			avatarUrl: "",
			stars: 500,
			updatedAt: TEST_TIMESTAMP,
			firstSeen: TEST_TIMESTAMP,
			hotRank: 1,
			isPreRelease: true,
			appFirstSeen: { [ALPHA_PACKAGE]: TEST_TIMESTAMP },
			patches: [
				{
					name: "Theme controls",
					description: "Custom themes",
					compatiblePackagesKey: 1,
				},
			],
		},
	],
	compatibilities: [
		[{ packageName: ALPHA_PACKAGE }, { packageName: BETA_PACKAGE }],
		[
			{
				packageName: ALPHA_PACKAGE,
				targets: [{ version: null }, { version: "2.0" }],
			},
		],
	],
	store: {
		[ALPHA_PACKAGE]: {
			name: "Alpha Player",
			iconUrl: "",
			description: "Video playback",
			minInstalls: 1000,
			category: "Video Players & Editors",
			firstSeen: TEST_TIMESTAMP,
		},
		[BETA_PACKAGE]: {
			name: "Beta Reader",
			iconUrl: "",
			description: "Đọc sách ngoại tuyến",
			minInstalls: 5000,
			category: "Books & Reference",
			firstSeen: TEST_TIMESTAMP,
		},
	},
};

export const previewMain = {
	patches: [
		{
			name: "Unlock premium",
			compatiblePackages: { [ALPHA_PACKAGE]: ["2.0"] },
			use: false,
		},
	],
};

export const previewDev = {
	patches: [
		...previewMain.patches,
		{
			name: "New controls",
			compatiblePackages: [
				{
					packageName: ALPHA_PACKAGE,
					targets: [{ version: "3.0", experimental: true }],
				},
			],
		},
	],
};
