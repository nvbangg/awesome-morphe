import { TriangleAlert } from "lucide-react";
import { useCallback, useMemo } from "react";
import { AppGrid } from "@/components/apps/AppGrid";
import { AppModal } from "@/components/apps/AppModal";
import { BundleModal } from "@/components/bundles/BundleModal";
import { BundlesTab } from "@/components/bundles/BundlesTab";
import { TestBundleInputModal } from "@/components/bundles/TestBundleInputModal";
import { TestBundleViewModal } from "@/components/bundles/TestBundleViewModal";
import { SkeletonGrid } from "@/components/common/CardGrid";
import { ControlBar } from "@/components/layout/ControlBar";
import { Footer } from "@/components/layout/Footer";
import { Header } from "@/components/layout/Header";
import { WhatsNewTab } from "@/components/whatsnew/WhatsNewTab";
import { BUNDLE_CATEGORY_OPTIONS } from "@/constants";
import { usePatchData } from "@/hooks/usePatchData";
import { useTestBundle } from "@/hooks/useTestBundle";
import { type NavigationTabType, useUrlSync } from "@/hooks/useUrlSync";
import { getAvailableCategories } from "@/services";

export default function App() {
	const {
		activeTab,
		selectedCategory,
		sortOrder,
		selectedAppPackageName,
		popupBundleKey,
		popupSearchQuery,
		updateUrl,
	} = useUrlSync();
	const {
		activeData,
		isLoading,
		errorMessage,
		whatsNewHistory,
		globalSearch,
		setGlobalSearch,
		stats,
	} = usePatchData(activeTab);

	const categories = useMemo(() => {
		if (activeTab === "bundles") return BUNDLE_CATEGORY_OPTIONS;
		if (!activeData) return [];
		return getAvailableCategories(activeData.appItems);
	}, [activeTab, activeData]);

	const handleTabChange = useCallback(
		(tab: NavigationTabType) => {
			setGlobalSearch("");
			updateUrl({ tab });
		},
		[setGlobalSearch, updateUrl],
	);

	const handleSortOrderChange = useCallback(
		(sort: string) => updateUrl({ sort }),
		[updateUrl],
	);
	const handleCategoryChange = useCallback(
		(category: string) => updateUrl({ category }),
		[updateUrl],
	);
	const handleAppClick = useCallback(
		(packageName: string) => updateUrl({ app: packageName }),
		[updateUrl],
	);
	const handleBundleClick = useCallback(
		(bundleKey: string) => updateUrl({ bundle: bundleKey }),
		[updateUrl],
	);
	const handlePatchClick = useCallback(
		(packageName: string, patchName: string) =>
			updateUrl({ app: packageName, search: patchName }),
		[updateUrl],
	);
	const handleCloseAppModal = useCallback(
		() => updateUrl({ app: null, search: "" }),
		[updateUrl],
	);
	const handleCloseBundleModal = useCallback(
		() => updateUrl({ bundle: null, search: "" }),
		[updateUrl],
	);
	const handleSearchChange = useCallback(
		(search: string) => updateUrl({ search }),
		[updateUrl],
	);

	const {
		isTestBundleInputOpen,
		isTestBundleViewOpen,
		testBundleData,
		testBundleLoading,
		testBundleError,
		handleTestBundleSubmit,
		handleOpenTestBundle,
		handleCloseTestBundleInput,
		handleCloseTestBundleView,
	} = useTestBundle(activeData);

	return (
		<div className="min-h-screen bg-background text-foreground transition-colors duration-300">
			<Header />

			<section className="pt-1 pb-4" id="bundles">
				<div id="apps" />
				<div className="container mx-auto px-6 max-w-300">
					{errorMessage ? (
						<div className="my-8 p-4 rounded-xl border border-warning/30 bg-card flex items-start gap-3 text-warning">
							<TriangleAlert className="size-5 shrink-0 mt-0.5" />
							<div>
								<h3 className="font-bold text-sm text-foreground">Error</h3>
								<p className="text-sm text-foreground-muted">{errorMessage}</p>
							</div>
						</div>
					) : (
						<>
							<ControlBar
								activeTab={activeTab}
								onTabChange={handleTabChange}
								globalSearchQuery={globalSearch}
								onSearchQueryChange={setGlobalSearch}
								sortOrder={sortOrder}
								onSortOrderChange={handleSortOrderChange}
								selectedCategory={selectedCategory}
								onCategoryChange={handleCategoryChange}
								categories={categories}
								stats={stats}
							/>

							{isLoading ? (
								<SkeletonGrid />
							) : (
								<>
									{activeTab === "apps" && (
										<AppGrid
											activeData={activeData}
											sortOrder={sortOrder}
											selectedCategory={selectedCategory}
											globalSearch={globalSearch}
											onAppClick={handleAppClick}
										/>
									)}

									{activeTab === "bundles" && (
										<BundlesTab
											activeData={activeData}
											sortOrder={sortOrder}
											selectedCategory={selectedCategory}
											globalSearch={globalSearch}
											onBundleClick={handleBundleClick}
											onTestBundleClick={handleOpenTestBundle}
										/>
									)}

									{activeTab === "whats-new" && (
										<WhatsNewTab
											history={whatsNewHistory}
											isLoading={isLoading}
											activeData={activeData}
											onBundleClick={handleBundleClick}
											onAppClick={handleAppClick}
											onPatchClick={handlePatchClick}
										/>
									)}
								</>
							)}
						</>
					)}
				</div>
			</section>

			<Footer />

			<TestBundleInputModal
				isOpen={isTestBundleInputOpen}
				onClose={handleCloseTestBundleInput}
				onSubmit={handleTestBundleSubmit}
				isLoading={testBundleLoading}
				error={testBundleError}
			/>

			<TestBundleViewModal
				isOpen={isTestBundleViewOpen}
				onClose={handleCloseTestBundleView}
				data={testBundleData}
				activeData={activeData}
			/>

			<AppModal
				isOpen={!!selectedAppPackageName}
				onClose={handleCloseAppModal}
				packageName={selectedAppPackageName}
				activeData={activeData}
				searchQuery={popupSearchQuery}
				onSearchChange={handleSearchChange}
				isWhatsNew={activeTab === "whats-new"}
			/>

			<BundleModal
				isOpen={!!popupBundleKey}
				onClose={handleCloseBundleModal}
				bundleKey={popupBundleKey}
				activeData={activeData}
				searchQuery={popupSearchQuery}
				onSearchChange={handleSearchChange}
				isWhatsNew={activeTab === "whats-new"}
			/>
		</div>
	);
}
