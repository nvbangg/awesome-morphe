import { z } from "zod";
import { optionSchema } from "@/features/catalog/schema";

const optionalTextSchema = z
	.string()
	.nullish()
	.transform((value) => value ?? "");

const targetSchema = z.union([
	z.string().transform((version) => ({ version, isExperimental: false })),
	z
		.object({
			version: z.string().nullable(),
			isExperimental: z.boolean().optional(),
			experimental: z.boolean().optional(),
		})
		.transform(({ version, isExperimental, experimental }) =>
			version === null
				? null
				: {
						version,
						isExperimental: Boolean(isExperimental || experimental),
					},
		),
]);

const targetsSchema = z
	.array(targetSchema)
	.nullish()
	.transform((targets) =>
		(targets ?? []).flatMap((target) => (target === null ? [] : [target])),
	);

const compatibilitySchema = z.union([
	z.array(
		z.object({
			packageName: z.string(),
			targets: targetsSchema,
		}),
	),
	z.record(z.string(), targetsSchema).transform((packages) =>
		Object.entries(packages).map(([packageName, targets]) => ({
			packageName,
			targets,
		})),
	),
]);

const testPatchSchema = z
	.object({
		name: z.string().min(1),
		description: optionalTextSchema,
		default: z.boolean().optional(),
		use: z.boolean().optional(),
		options: z
			.array(
				optionSchema.extend({
					title: optionalTextSchema,
					description: optionalTextSchema,
				}),
			)
			.nullish()
			.transform((options) => options ?? []),
		compatiblePackages: compatibilitySchema
			.nullish()
			.transform((packages) => packages ?? []),
		firstSeen: z.number().optional(),
	})
	.transform(({ use, ...patch }) => ({
		...patch,
		default: (patch.default ?? use) !== false,
	}));

export const testBundleSchema = z.object({
	patches: z.array(testPatchSchema),
});

export type TestBundleArtifact = z.infer<typeof testBundleSchema>;
