import { useEffect, useMemo, useState } from "react";
import { fetchWhatsNewHistory, loadInitData } from "@/services";
import type { ActiveData, WhatsNewHistoryItem } from "@/types/data";

export function usePatchData(activeTab?: string) {
	const [activeData, setActiveData] = useState<ActiveData | null>(null);
	const [isLoading, setIsLoading] = useState(true);
	const [errorMessage, setErrorMessage] = useState("");
	const [whatsNewHistory, setWhatsNewHistory] = useState<WhatsNewHistoryItem[]>(
		[],
	);
	const [globalSearch, setGlobalSearch] = useState("");

	useEffect(() => {
		let isComponentMounted = true;
		loadInitData()
			.then((loadedData) => {
				if (isComponentMounted) {
					setActiveData(loadedData);
					setIsLoading(false);
				}
			})
			.catch((error: unknown) => {
				if (isComponentMounted) {
					setErrorMessage(
						error instanceof Error ? error.message : "Failed to load data",
					);
					setIsLoading(false);
				}
			});
		return () => {
			isComponentMounted = false;
		};
	}, []);

	useEffect(() => {
		if (activeTab !== "whats-new" || whatsNewHistory.length > 0) return;

		let isComponentMounted = true;
		fetchWhatsNewHistory()
			.then((history) => {
				if (isComponentMounted) {
					setWhatsNewHistory(history);
				}
			})
			.catch(() => {
				// Ignore fetch errors to keep previous state or fallback
			});

		return () => {
			isComponentMounted = false;
		};
	}, [activeTab, whatsNewHistory.length]);

	const stats = useMemo(
		() =>
			activeData?.stats || {
				bundlesCount: 0,
				appsCount: 0,
				categoryAppsCount: {},
				categoryBundlesCount: {},
			},
		[activeData],
	);

	return {
		activeData,
		isLoading,
		errorMessage,
		whatsNewHistory,
		globalSearch,
		setGlobalSearch,
		stats,
	};
}
