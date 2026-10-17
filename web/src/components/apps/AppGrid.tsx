import { memo, useDeferredValue, useMemo } from "react";
import { CardGrid, EmptyState } from "@/components/common/CardGrid";
import { ITEMS_PER_PAGE } from "@/constants";
import { useInfiniteScroll } from "@/hooks/useInfiniteScroll";
import { getAppItems } from "@/services";
import type { ActiveData } from "@/types/data";
import { AppCard } from "./AppCard";

interface AppGridProps {
	activeData: ActiveData | null;
	sortOrder: string;
	selectedCategory?: string;
	globalSearch: string;
	onAppClick: (packageName: string) => void;
}

export const AppGrid = memo(function AppGrid({
	activeData,
	sortOrder,
	selectedCategory = "all",
	globalSearch,
	onAppClick,
}: AppGridProps) {
	const deferredSearch = useDeferredValue(globalSearch);

	const appList = useMemo(() => {
		if (!activeData) return [];
		return getAppItems(
			activeData.appItems,
			deferredSearch,
			sortOrder,
			selectedCategory,
		);
	}, [activeData, sortOrder, selectedCategory, deferredSearch]);

	const { visibleItems, loadMoreRef, hasMore } = useInfiniteScroll(
		appList,
		ITEMS_PER_PAGE,
	);

	if (appList.length === 0) {
		return <EmptyState message="No apps match your search" />;
	}

	return (
		<CardGrid hasMore={hasMore} loadMoreRef={loadMoreRef}>
			{visibleItems.map((appItem) => (
				<AppCard
					key={appItem.packageName}
					appItem={appItem}
					onClick={onAppClick}
				/>
			))}
		</CardGrid>
	);
});
