"use client";

import { AppGrid } from "./AppGrid";
import { useCatalog } from "./api";
import { useCatalogSearch } from "./CatalogShell";
import { useCatalogParams } from "./params";
import { getAvailableCategories } from "./search";

export function AppsView() {
	const { data } = useCatalog();
	const [params, setParams] = useCatalogParams();
	const search = useCatalogSearch();
	const category = getAvailableCategories(data?.appItems ?? []).some(
		(option) => option.value === params.category,
	)
		? params.category
		: "all";
	return (
		<AppGrid
			activeData={data ?? null}
			sortOrder={params.sort}
			selectedCategory={category}
			globalSearch={search}
			onAppClick={(app) =>
				setParams({ app, github: "", gitlab: "", patch: "" })
			}
		/>
	);
}
