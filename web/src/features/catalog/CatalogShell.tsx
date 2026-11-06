"use client";

import { TriangleAlert } from "lucide-react";
import { usePathname } from "next/navigation";
import { createContext, useContext, useState } from "react";
import { ZodError } from "zod";
import { SkeletonGrid } from "@/components/common/CardGrid";
import { BUNDLE_CATEGORY_OPTIONS } from "@/constants";
import { TestBundleController } from "@/features/test-bundle/TestBundleController";
import { useCatalog } from "./api";
import { CatalogDialog } from "./CatalogDialog";
import { ControlBar } from "./ControlBar";
import { type CatalogTab, useCatalogParams } from "./params";
import { getAvailableCategories } from "./search";

const SearchContext = createContext("");

export function useCatalogSearch() {
	return useContext(SearchContext);
}

export function CatalogShell({ children }: { children: React.ReactNode }) {
	const pathname = usePathname();
	const tab: CatalogTab =
		pathname === "/bundles"
			? "bundles"
			: pathname === "/whats-new"
				? "whats-new"
				: "apps";
	return (
		<>
			<CatalogContent key={tab} tab={tab}>
				{children}
			</CatalogContent>
			<CatalogDialog isWhatsNew={tab === "whats-new"} />
			<TestBundleController />
		</>
	);
}

function CatalogContent({
	tab,
	children,
}: {
	tab: CatalogTab;
	children: React.ReactNode;
}) {
	const { data, error, isPending } = useCatalog();
	const [params, setParams] = useCatalogParams();
	const [search, setSearch] = useState("");
	const categories =
		tab === "bundles"
			? BUNDLE_CATEGORY_OPTIONS
			: getAvailableCategories(data?.appItems ?? []);
	const category = categories.some((option) => option.key === params.category)
		? params.category
		: "all";
	return (
		<main className="pt-1 pb-4" aria-label="Catalog">
			<div className="container mx-auto px-6 max-w-300">
				{error ? (
					<div
						role="alert"
						className="my-8 p-4 rounded-xl border border-warning/30 bg-card flex items-start gap-3 text-warning"
					>
						<TriangleAlert className="size-5 shrink-0 mt-0.5" />
						<div>
							<h3 className="font-bold text-sm text-foreground">Error</h3>
							<p className="text-sm text-foreground-muted">
								{error instanceof ZodError
									? "Catalog data is invalid. Please try again later."
									: error.message}
							</p>
						</div>
					</div>
				) : (
					<>
						<ControlBar
							activeTab={tab}
							globalSearchQuery={search}
							onSearchQueryChange={setSearch}
							sortOrder={params.sort}
							onSortOrderChange={(value) =>
								setParams({ sort: value as typeof params.sort })
							}
							selectedCategory={category}
							onCategoryChange={(category) => setParams({ category })}
							categories={categories}
							stats={
								data?.stats ?? {
									appsCount: 0,
									bundlesCount: 0,
									categoryAppsCount: {},
									categoryBundlesCount: {},
								}
							}
						/>
						{isPending ? (
							<SkeletonGrid />
						) : (
							<SearchContext.Provider value={search}>
								{children}
							</SearchContext.Provider>
						)}
					</>
				)}
			</div>
		</main>
	);
}
