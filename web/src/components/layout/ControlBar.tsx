import { useMemo } from "react";
import {
  Grid,
  Layers,
  Sparkles,
  Shapes,
  ArrowDownWideNarrow,
} from "lucide-react";
import { NavigationTabType as TabType } from "@/hooks/useUrlSync";
import { ActiveStats } from "@/types/data";
import { Badge } from "@/components/common/Badge";
import { SearchInput } from "@/components/common/SearchInput";
import { CustomSelect } from "@/components/common/CustomSelect";

interface ControlBarProps {
  activeTab: TabType;
  onTabChange: (tab: TabType) => void;
  globalSearchQuery: string;
  onSearchQueryChange: (searchValue: string) => void;
  sortOrder: string;
  onSortOrderChange: (sortValue: string) => void;
  selectedCategory?: string;
  onCategoryChange?: (categoryValue: string) => void;
  categories?: { key: string; label: string }[];
  stats: ActiveStats;
}

const BUNDLE_SORT_OPTIONS = [
  { key: "default", label: "Hot" },
  { key: "new", label: "New" },
  { key: "updated", label: "Recently updated" },
  { key: "stars", label: "Most stars" },
  { key: "apps", label: "Most apps" },
  { key: "patches", label: "Most patches" },
  { key: "alpha", label: "Alphabetical" },
];

const APP_SORT_OPTIONS = [
  { key: "default", label: "Most downloads" },
  { key: "new", label: "New" },
  { key: "updated", label: "Recently updated" },
  { key: "patches", label: "Most patches" },
  { key: "alpha", label: "Alphabetical" },
];

const TAB_ITEM_BASE =
  "flex-1 sm:flex-initial h-full px-3.5 text-xs rounded-lg cursor-pointer transition-all flex items-center justify-center gap-1.5 outline-none border-none select-none";

export function ControlBar({
  activeTab,
  onTabChange,
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

  const count = useMemo(() => {
    if (activeTab === "apps") {
      if (!selectedCategory || selectedCategory === "all") {
        return stats.appsCount;
      }
      return stats.categoryAppsCount?.[selectedCategory] ?? 0;
    }
    if (!selectedCategory || selectedCategory === "all") {
      return stats.bundlesCount;
    }
    return stats.categoryBundlesCount?.[selectedCategory] ?? 0;
  }, [activeTab, selectedCategory, stats]);

  return (
    <div
      className="flex flex-col sm:flex-row sm:flex-wrap items-center gap-3 sm:gap-4 mt-2 mb-3 relative"
      id="browse-bar"
    >
      <nav
        role="tablist"
        aria-label="Navigation Tabs"
        className="w-full sm:w-auto h-10 p-1 bg-card border border-divider rounded-xl flex items-center justify-between sm:justify-start box-border"
      >
        <button
          type="button"
          role="tab"
          id="tab-apps"
          aria-selected={activeTab === "apps"}
          aria-controls="apps"
          onClick={() => onTabChange("apps")}
          className={`${TAB_ITEM_BASE} ${
            activeTab === "apps"
              ? "bg-background dark:bg-divider text-foreground font-bold shadow-sm"
              : "text-foreground-muted hover:text-foreground font-semibold"
          }`}
        >
          <Grid className="size-4 shrink-0 text-primary" />
          <span>Apps</span>
        </button>

        <div className="w-px h-4 bg-divider shrink-0 mx-0.5" />

        <button
          type="button"
          role="tab"
          id="tab-bundles"
          aria-selected={activeTab === "bundles"}
          aria-controls="bundles"
          onClick={() => onTabChange("bundles")}
          className={`${TAB_ITEM_BASE} ${
            activeTab === "bundles"
              ? "bg-background dark:bg-divider text-foreground font-bold shadow-sm"
              : "text-foreground-muted hover:text-foreground font-semibold"
          }`}
        >
          <Layers className="size-4 shrink-0 text-secondary" />
          <span>Bundles</span>
        </button>

        <div className="w-px h-4 bg-divider shrink-0 mx-0.5" />

        <button
          type="button"
          role="tab"
          id="tab-whats-new"
          aria-selected={activeTab === "whats-new"}
          aria-controls="whats-new"
          onClick={() => onTabChange("whats-new")}
          className={`${TAB_ITEM_BASE} ${
            activeTab === "whats-new"
              ? "bg-background dark:bg-divider text-foreground font-bold shadow-sm"
              : "text-foreground-muted hover:text-foreground font-semibold"
          }`}
        >
          <Sparkles className="size-4 shrink-0 text-warning fill-current" />
          <span className="whitespace-nowrap">What's New</span>
        </button>
      </nav>

      {activeTab === "whats-new" ? (
        <div className="w-full sm:w-auto sm:absolute sm:left-1/2 sm:top-1/2 sm:-translate-x-1/2 sm:-translate-y-1/2 flex items-center justify-center gap-2.5 text-sm text-foreground font-semibold py-1 select-text">
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
              onChange={(sortValue) => onSortOrderChange(sortValue)}
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

          <div className="flex items-center gap-3 w-full sm:w-auto flex-1 min-w-70">
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
