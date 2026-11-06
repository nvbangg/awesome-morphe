import { z } from "zod";

export const versionSchema = z.object({
	version: z.string(),
	isExperimental: z.boolean().optional(),
});

export const optionSchema = z.object({
	key: z.string(),
	title: z.string().default(""),
	description: z.string().default(""),
});

const patchSchema = z.object({
	name: z.string(),
	description: z.string().default(""),
	default: z.boolean().optional(),
	options: z.array(optionSchema).optional(),
	isPreRelease: z.boolean().optional(),
	firstSeen: z.number().optional(),
	compatiblePackagesKey: z.number().int().nonnegative().optional(),
});

export const compatibilitySchema = z.object({
	packageName: z.string(),
	targets: z
		.array(versionSchema.extend({ version: z.string().nullable() }))
		.optional(),
});

export const appMetadataSchema = z.object({
	name: z.string(),
	iconUrl: z.string(),
	description: z.string().default(""),
	minInstalls: z.number(),
	category: z.string(),
	firstSeen: z.number(),
	updatedAt: z.number().optional(),
	isPreRelease: z.boolean().optional(),
});

export const bundleSchema = z.object({
	source: z.enum(["github", "gitlab"]),
	repo: z.string(),
	name: z.string(),
	repoDescription: z.string(),
	avatarUrl: z.string(),
	stars: z.number(),
	updatedAt: z.number(),
	firstSeen: z.number(),
	hotRank: z.number(),
	isPreRelease: z.boolean().optional(),
	isArchived: z.boolean().optional(),
	isOfficial: z.boolean().optional(),
	appFirstSeen: z.record(z.string(), z.number()),
	appUpdates: z.record(z.string(), z.number()).optional(),
	patches: z.array(patchSchema),
});

export const catalogSchema = z.object({
	bundles: z.array(bundleSchema),
	compatibilities: z.array(z.array(compatibilitySchema)),
	store: z.record(z.string(), appMetadataSchema),
});

export type CatalogArtifact = z.infer<typeof catalogSchema>;
