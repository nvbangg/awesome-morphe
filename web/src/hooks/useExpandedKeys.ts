import { useCallback, useState } from "react";

export function useExpandedKeys(
	isOpen: boolean,
	keys: string[],
	searchQuery: string = "",
) {
	const shouldAutoExpand = keys.length === 1 || searchQuery.trim().length > 0;
	const [expandedKeys, setExpandedKeys] = useState(
		() => new Set(isOpen && shouldAutoExpand ? keys : []),
	);
	const [prevDeps, setPrevDeps] = useState({
		isOpen,
		searchQuery,
		keys,
	});

	if (
		prevDeps.isOpen !== isOpen ||
		prevDeps.searchQuery !== searchQuery ||
		prevDeps.keys.length !== keys.length ||
		keys.some((key, index) => key !== prevDeps.keys[index])
	) {
		setPrevDeps({ isOpen, searchQuery, keys });
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
