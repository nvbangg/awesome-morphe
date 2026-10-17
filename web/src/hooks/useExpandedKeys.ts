import { useCallback, useState } from "react";

export function useExpandedKeys(
	isOpen: boolean,
	keys: string[],
	searchQuery: string = "",
) {
	const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set());
	const [prevDeps, setPrevDeps] = useState<{
		isOpen: boolean;
		searchQuery: string;
		keysLength: number;
	}>({
		isOpen,
		searchQuery,
		keysLength: keys.length,
	});

	const shouldAutoExpand = keys.length === 1 || searchQuery.trim().length > 0;

	if (
		prevDeps.isOpen !== isOpen ||
		prevDeps.searchQuery !== searchQuery ||
		prevDeps.keysLength !== keys.length
	) {
		setPrevDeps({ isOpen, searchQuery, keysLength: keys.length });
		setExpandedKeys(isOpen && shouldAutoExpand ? new Set(keys) : new Set());
	}

	const toggleKey = useCallback((key: string) => {
		setExpandedKeys((prev) => {
			const next = new Set(prev);
			if (next.has(key)) {
				next.delete(key);
			} else {
				next.add(key);
			}
			return next;
		});
	}, []);

	return { expandedKeys, toggleKey };
}
