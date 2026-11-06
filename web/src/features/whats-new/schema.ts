import { z } from "zod";

const appChangeSchema = z.object({
	patches: z.array(z.string()),
	isNew: z.boolean().optional(),
	appName: z.string().optional(),
});
const bundleChangeSchema = z.object({
	apps: z.record(z.string(), appChangeSchema).optional(),
	isNew: z.boolean().optional(),
});

export const historySchema = z.array(
	z.object({
		date: z.string(),
		bundles: z.record(z.string(), bundleChangeSchema),
	}),
);

export type WhatsNewAppChange = z.infer<typeof appChangeSchema>;
export type WhatsNewBundleChange = z.infer<typeof bundleChangeSchema>;
export type WhatsNewHistoryItem = z.infer<typeof historySchema>[number];
