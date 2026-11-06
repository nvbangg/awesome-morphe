"use client";

import { useCatalog } from "./api";
import { BundleGrid } from "./BundleGrid";
import { useCatalogSearch } from "./CatalogShell";
import { getBundleParams, setTestBundle, useCatalogParams } from "./params";

export function BundlesView() {
	const { data } = useCatalog();
	const [params, setParams] = useCatalogParams();
	const search = useCatalogSearch();
	return (
		<>
			<div className="text-sm sm:text-base text-foreground-muted mb-4 px-1 text-right">
				Bundle not found?{" "}
				<button
					type="button"
					onClick={() => setTestBundle()}
					className="font-semibold text-primary hover:underline hover:opacity-80 transition-opacity cursor-pointer"
				>
					Test bundle
				</button>
				{" | "}
				<a
					href="https://github.com/nvbangg/awesome-morphe/issues/new?template=bundle-request.yml"
					target="_blank"
					className="font-semibold text-primary hover:underline hover:opacity-80 transition-opacity"
					rel="noopener"
				>
					Submit Bundle
				</a>
			</div>
			<BundleGrid
				activeData={data ?? null}
				sortOrder={params.sort}
				selectedCategory={params.category}
				globalSearch={search}
				onBundleClick={(bundle) => setParams(getBundleParams(bundle))}
			/>
		</>
	);
}
