import { queryOptions, useQuery } from "@tanstack/react-query";
import { fetchJson } from "@/lib/http";
import { buildCatalog } from "./model";
import { catalogSchema } from "./schema";

const catalogQuery = queryOptions({
	queryKey: ["catalog"],
	queryFn: async ({ signal }) =>
		buildCatalog(catalogSchema.parse(await fetchJson("/bundles.json", signal))),
	staleTime: Infinity,
	gcTime: Infinity,
});

export function useCatalog() {
	return useQuery(catalogQuery);
}
