import type { ActiveData } from "@/types/data";
import { BundleGrid } from "./BundleGrid";

interface BundlesTabProps {
	activeData: ActiveData | null;
	sortOrder: string;
	selectedCategory?: string;
	globalSearch: string;
	onBundleClick: (bundleKey: string) => void;
	onTestBundleClick: () => void;
}

export function BundlesTab({
	activeData,
	sortOrder,
	selectedCategory = "all",
	globalSearch,
	onBundleClick,
	onTestBundleClick,
}: BundlesTabProps) {
	return (
		<>
			<div className="text-sm sm:text-base text-foreground-muted mb-4 px-1 text-right">
				Bundle not found?{" "}
				<button
					type="button"
					onClick={onTestBundleClick}
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
				activeData={activeData}
				sortOrder={sortOrder}
				selectedCategory={selectedCategory}
				globalSearch={globalSearch}
				onBundleClick={onBundleClick}
			/>
		</>
	);
}
