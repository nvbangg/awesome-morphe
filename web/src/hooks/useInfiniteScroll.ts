import { useCallback, useState } from "react";
import { ITEMS_PER_PAGE, UI_SCROLL_ROOT_MARGIN } from "@/constants";

export function useInfiniteScroll<T>(items: T[], chunkSize = ITEMS_PER_PAGE) {
	const [visibleCount, setVisibleCount] = useState(chunkSize);

	const [prevItems, setPrevItems] = useState(items);
	if (items !== prevItems) {
		setPrevItems(items);
		setVisibleCount(chunkSize);
	}

	const loadMoreRef = useCallback(
		(element: HTMLDivElement | null) => {
			if (!element) return;

			const observer = new IntersectionObserver(
				([entry]) => {
					if (entry.isIntersecting) {
						setVisibleCount((previous) =>
							Math.min(previous + chunkSize, items.length),
						);
					}
				},
				{ rootMargin: UI_SCROLL_ROOT_MARGIN },
			);

			observer.observe(element);
			return () => observer.disconnect();
		},
		[chunkSize, items.length],
	);

	const visibleItems = items.slice(0, visibleCount);
	const hasMore = visibleCount < items.length;

	return { visibleItems, loadMoreRef, hasMore };
}
