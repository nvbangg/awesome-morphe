import { useCallback, useEffect, useState } from "react";
import { fetchTestBundle, type TestBundleData } from "@/services";
import type { ActiveData } from "@/types/data";

export function useTestBundle(activeData: ActiveData | null) {
	const [isTestBundleInputOpen, setIsTestBundleInputOpen] = useState(false);
	const [isTestBundleViewOpen, setIsTestBundleViewOpen] = useState(false);
	const [testBundleData, setTestBundleData] = useState<TestBundleData | null>(
		null,
	);
	const [testBundleLoading, setTestBundleLoading] = useState(false);
	const [testBundleError, setTestBundleError] = useState("");

	const loadTestBundleFromUrl = useCallback(
		async (link: string, isFromSubmit = false) => {
			if (!activeData) return;
			setTestBundleLoading(true);
			setTestBundleError("");
			try {
				const data = await fetchTestBundle(link);
				setTestBundleData(data);
				setIsTestBundleInputOpen(false);
				setIsTestBundleViewOpen(true);

				if (isFromSubmit) {
					const repoInfo = data.repoName;
					const sourceParam = data.source === "gitlab" ? "gitlab" : "github";
					window.history.replaceState(
						null,
						"",
						`${window.location.pathname}?${sourceParam}=${repoInfo}&test-bundle#bundles`,
					);
				}
			} catch (error: unknown) {
				setTestBundleError(
					error instanceof Error
						? error.message
						: "Failed to load bundle data. Please check the URL and try again.",
				);
				if (!isFromSubmit) {
					setIsTestBundleInputOpen(true);
				}
			} finally {
				setTestBundleLoading(false);
			}
		},
		[activeData],
	);

	const handleTestBundleSubmit = useCallback(
		async (link: string) => {
			await loadTestBundleFromUrl(link, true);
		},
		[loadTestBundleFromUrl],
	);

	useEffect(() => {
		if (!activeData) return;
		const handleUrlState = () => {
			const searchParams = new URLSearchParams(window.location.search);
			const isTestBundle =
				searchParams.has("test-bundle") ||
				window.location.hash.includes("test-bundle");

			if (isTestBundle) {
				const githubRepo = searchParams.get("github");
				const gitlabRepo = searchParams.get("gitlab");

				if (githubRepo) {
					loadTestBundleFromUrl(`https://github.com/${githubRepo}`);
				} else if (gitlabRepo) {
					loadTestBundleFromUrl(`https://gitlab.com/${gitlabRepo}`);
				} else {
					setIsTestBundleInputOpen(true);
				}
			}
		};
		handleUrlState();
		window.addEventListener("popstate", handleUrlState);
		window.addEventListener("hashchange", handleUrlState);
		return () => {
			window.removeEventListener("popstate", handleUrlState);
			window.removeEventListener("hashchange", handleUrlState);
		};
	}, [activeData, loadTestBundleFromUrl]);

	const handleOpenTestBundle = useCallback(() => {
		setTestBundleError("");
		setIsTestBundleInputOpen(true);
		window.history.replaceState(
			null,
			"",
			`${window.location.pathname}?test-bundle#bundles`,
		);
	}, []);

	const handleCloseTestBundleInput = useCallback(() => {
		setTestBundleError("");
		setIsTestBundleInputOpen(false);
		if (window.location.search.includes("test-bundle")) {
			window.history.replaceState(
				null,
				"",
				`${window.location.pathname}#bundles`,
			);
		}
	}, []);

	const handleCloseTestBundleView = useCallback(() => {
		setIsTestBundleViewOpen(false);
		window.history.replaceState(
			null,
			"",
			`${window.location.pathname}#bundles`,
		);
	}, []);

	return {
		isTestBundleInputOpen,
		isTestBundleViewOpen,
		testBundleData,
		testBundleLoading,
		testBundleError,
		handleTestBundleSubmit,
		handleOpenTestBundle,
		handleCloseTestBundleInput,
		handleCloseTestBundleView,
	};
}
