import {
	ArrowDownWideNarrow,
	Grid,
	Layers,
	Shapes,
	Sparkles,
} from "lucide-react";
import Link from "next/link";
import { Badge } from "@/components/common/Badge";
import { CustomSelect } from "@/components/common/CustomSelect";
import { SearchInput } from "@/components/common/SearchInput";
import type { CatalogTab as TabType } from "./params";
import type { ActiveStats } from "./types";

interface ControlBarProps {
	activeTab: TabType;
	globalSearchQuery: string;
	onSearchQueryChange: (searchValue: string) => void;
	sortOrder: string;
	onSortOrderChange: (sortValue: string) => void;
	selectedCategory?: string;
	onCategoryChange?: (categoryValue: string) => void;
	categories?: { value: string; label: string }[];
	stats: ActiveStats;
}

const BUNDLE_SORT_OPTIONS = [
	{ value: "default", label: "Hot" },
	{ value: "new", label: "New" },
	{ value: "updated", label: "Recently updated" },
	{ value: "stars", label: "Most stars" },
	{ value: "apps", label: "Most apps" },
	{ value: "patches", label: "Most patches" },
	{ value: "alpha", label: "Alphabetical" },
];

const APP_SORT_OPTIONS = [
	{ value: "default", label: "Most downloads" },
	{ value: "new", label: "New" },
	{ value: "updated", label: "Recently updated" },
	{ value: "patches", label: "Most patches" },
	{ value: "alpha", label: "Alphabetical" },
];

const TAB_ITEM_BASE =
	"flex-1 sm:flex-initial h-full px-3.5 max-[360px]:px-2 text-xs rounded-lg cursor-pointer transition-all flex items-center justify-center gap-1.5 outline-none border-none select-none";

export function ControlBar({
	activeTab,
	globalSearchQuery,
	onSearchQueryChange,
	sortOrder,
	onSortOrderChange,
	selectedCategory = "all",
	onCategoryChange,
	categories = [],
	stats,
}: ControlBarProps) {
	const sortOptions =
		activeTab === "bundles" ? BUNDLE_SORT_OPTIONS : APP_SORT_OPTIONS;

	const categoryCounts =
		activeTab === "apps" ? stats.categoryAppsCount : stats.categoryBundlesCount;
	const totalCount =
		activeTab === "apps" ? stats.appsCount : stats.bundlesCount;
	const count =
		!selectedCategory || selectedCategory === "all"
			? totalCount
			: (categoryCounts[selectedCategory] ?? 0);

	return (
		<div
			className="flex flex-col sm:flex-row sm:flex-wrap items-center gap-3 sm:gap-4 mt-2 mb-3 relative"
			id="browse-bar"
		>
			<nav
				aria-label="Navigation Tabs"
				className="w-full sm:w-auto h-10 p-1 bg-card border border-divider rounded-xl flex items-center justify-between sm:justify-start box-border"
			>
				<Link
					id="tab-apps"
					aria-current={activeTab === "apps" ? "page" : undefined}
					href="/"
					scroll={false}
					className={`${TAB_ITEM_BASE} ${
						activeTab === "apps"
							? "bg-background dark:bg-divider text-foreground font-bold shadow-sm"
							: "text-foreground-muted hover:text-foreground font-semibold"
					}`}
				>
					<Grid className="size-4 shrink-0 text-primary" />
					<span>Apps</span>
				</Link>

				<div className="w-px h-4 bg-divider shrink-0 mx-0.5" />

				<Link
					id="tab-bundles"
					aria-current={activeTab === "bundles" ? "page" : undefined}
					href="/bundles"
					scroll={false}
					className={`${TAB_ITEM_BASE} ${
						activeTab === "bundles"
							? "bg-background dark:bg-divider text-foreground font-bold shadow-sm"
							: "text-foreground-muted hover:text-foreground font-semibold"
					}`}
				>
					<Layers className="size-4 shrink-0 text-secondary" />
					<span>Bundles</span>
				</Link>

				<div className="w-px h-4 bg-divider shrink-0 mx-0.5" />

				<Link
					id="tab-whats-new"
					aria-current={activeTab === "whats-new" ? "page" : undefined}
					href="/whats-new"
					scroll={false}
					className={`${TAB_ITEM_BASE} ${
						activeTab === "whats-new"
							? "bg-background dark:bg-divider text-foreground font-bold shadow-sm"
							: "text-foreground-muted hover:text-foreground font-semibold"
					}`}
				>
					<Sparkles className="size-4 shrink-0 text-warning fill-current" />
					<span className="whitespace-nowrap">What's New</span>
				</Link>
			</nav>

			{activeTab === "whats-new" ? (
				<div className="w-full sm:w-auto lg:absolute lg:left-1/2 lg:top-1/2 lg:-translate-x-1/2 lg:-translate-y-1/2 flex items-center justify-center gap-2.5 text-sm text-foreground font-semibold py-1 select-text">
					<span className="relative flex size-2 shrink-0">
						<span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-secondary opacity-75"></span>
						<span className="relative inline-flex rounded-full size-2 bg-secondary"></span>
					</span>
					<span className="whitespace-nowrap">
						Recently added bundles, apps & patches
					</span>
				</div>
			) : (
				<>
					<div className="w-full sm:w-52 shrink-0">
						<CustomSelect
							value={sortOrder || "default"}
							onChange={onSortOrderChange}
							options={sortOptions}
							icon={ArrowDownWideNarrow}
							ariaLabel="Sort order"
							className="w-full"
						/>
					</div>

					{categories.length > 0 && (
						<div className="w-full sm:w-56 shrink-0">
							<CustomSelect
								value={selectedCategory || "all"}
								onChange={(categoryValue) => onCategoryChange?.(categoryValue)}
								options={categories}
								icon={Shapes}
								ariaLabel="Category filter"
								className="w-full"
							/>
						</div>
					)}

					<div className="flex items-center gap-3 w-full sm:w-auto flex-1 min-w-0">
						<SearchInput
							id="search-input"
							value={globalSearchQuery}
							onChange={onSearchQueryChange}
							placeholder={
								activeTab === "apps" ? "Search apps…" : "Search bundles…"
							}
							className="flex-1 min-w-0"
						/>
						<div className="shrink-0 sm:ml-auto">
							<Badge variant="count">
								{activeTab === "apps"
									? `${count.toLocaleString()} Apps`
									: `${count.toLocaleString()} Bundles`}
							</Badge>
						</div>
					</div>
				</>
			)}
		</div>
	);
}
