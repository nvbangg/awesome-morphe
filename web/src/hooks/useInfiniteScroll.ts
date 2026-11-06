import { useEffect, useRef, useState } from "react";
import { ITEMS_PER_PAGE, UI_SCROLL_ROOT_MARGIN } from "@/constants";

export function useInfiniteScroll<T>(items: T[], chunkSize = ITEMS_PER_PAGE) {
	const [visibleCount, setVisibleCount] = useState(chunkSize);
	const loadMoreRef = useRef<HTMLDivElement | null>(null);

	const [prevItems, setPrevItems] = useState(items);
	if (items !== prevItems) {
		setPrevItems(items);
		setVisibleCount(chunkSize);
	}

	useEffect(() => {
		const currentElement = loadMoreRef.current;
		if (!currentElement) return;

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

		observer.observe(currentElement);
		return () => observer.disconnect();
	}, [chunkSize, items.length]);

	const visibleItems = items.slice(0, visibleCount);
	const hasMore = visibleCount < items.length;

	return { visibleItems, loadMoreRef, hasMore };
}
