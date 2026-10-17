import { useCallback, useEffect, useRef, useState } from "react";
import { ITEMS_PER_PAGE, UI_SCROLL_ROOT_MARGIN } from "@/constants";

export function useInfiniteScroll<T>(items: T[], chunkSize = ITEMS_PER_PAGE) {
	const [visibleCount, setVisibleCount] = useState(chunkSize);
	const observerRef = useRef<IntersectionObserver | null>(null);
	const loadMoreRef = useRef<HTMLDivElement | null>(null);

	const [prevItems, setPrevItems] = useState(items);
	if (items !== prevItems) {
		setPrevItems(items);
		setVisibleCount(chunkSize);
	}

	const handleObserver = useCallback(
		(entries: IntersectionObserverEntry[]) => {
			const target = entries[0];
			if (target.isIntersecting) {
				setVisibleCount((prevCount) =>
					Math.min(prevCount + chunkSize, items.length),
				);
			}
		},
		[chunkSize, items.length],
	);

	useEffect(() => {
		const currentElement = loadMoreRef.current;
		if (!currentElement) return;

		observerRef.current = new IntersectionObserver(handleObserver, {
			root: null,
			rootMargin: UI_SCROLL_ROOT_MARGIN,
			threshold: 0,
		});

		observerRef.current.observe(currentElement);

		return () => {
			observerRef.current?.disconnect();
		};
	}, [handleObserver]);

	const visibleItems = items.slice(0, visibleCount);
	const hasMore = visibleCount < items.length;

	return { visibleItems, loadMoreRef, hasMore };
}
