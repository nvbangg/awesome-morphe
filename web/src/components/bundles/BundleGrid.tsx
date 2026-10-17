import { memo, useDeferredValue, useMemo } from "react";
import { CardGrid, EmptyState } from "@/components/common/CardGrid";
import { ITEMS_PER_PAGE } from "@/constants";
import { useInfiniteScroll } from "@/hooks/useInfiniteScroll";
import { getBundleItems } from "@/services";
import type { ActiveData } from "@/types/data";
import { BundleCard } from "./BundleCard";

interface BundleGridProps {
	activeData: ActiveData | null;
	sortOrder: string;
	selectedCategory?: string;
	globalSearch: string;
	onBundleClick: (bundleKey: string) => void;
}

export const BundleGrid = memo(function BundleGrid({
	activeData,
	sortOrder,
	selectedCategory = "all",
	globalSearch,
	onBundleClick,
}: BundleGridProps) {
	const deferredSearch = useDeferredValue(globalSearch);

	const processedBundles = useMemo(() => {
		if (!activeData) return [];
		return getBundleItems(
			activeData.bundles,
			deferredSearch,
			sortOrder,
			selectedCategory,
		);
	}, [activeData, sortOrder, selectedCategory, deferredSearch]);

	const { visibleItems, loadMoreRef, hasMore } = useInfiniteScroll(
		processedBundles,
		ITEMS_PER_PAGE,
	);

	if (processedBundles.length === 0) {
		return <EmptyState message="No bundles match your search" />;
	}

	return (
		<CardGrid hasMore={hasMore} loadMoreRef={loadMoreRef}>
			{visibleItems.map((bundleItem) => (
				<BundleCard
					key={bundleItem.key}
					bundleItem={bundleItem}
					onClick={onBundleClick}
				/>
			))}
		</CardGrid>
	);
});
