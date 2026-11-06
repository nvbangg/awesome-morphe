import { queryOptions } from "@tanstack/react-query";
import { fetchJson } from "@/lib/http";
import { historySchema } from "./schema";

export const historyQuery = queryOptions({
	queryKey: ["whats-new"],
	queryFn: async ({ signal }) =>
		historySchema.parse(await fetchJson("/whats-new.json", signal)),
	staleTime: Infinity,
	gcTime: Infinity,
});
