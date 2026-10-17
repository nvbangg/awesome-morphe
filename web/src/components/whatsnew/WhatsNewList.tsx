import { Calendar, Loader2, Sparkles } from "lucide-react";
import { WHATS_NEW_DAYS_PER_PAGE } from "@/constants";
import { useInfiniteScroll } from "@/hooks/useInfiniteScroll";
import type { ActiveData, WhatsNewHistoryItem } from "@/types/data";
import { WhatsNewBundleCard } from "./WhatsNewBundleCard";

interface WhatsNewListProps {
	history: WhatsNewHistoryItem[];
	isLoading: boolean;
	activeData: ActiveData | null;
	onBundleClick: (bundleKey: string) => void;
	onAppClick: (packageName: string) => void;
	onPatchClick: (packageName: string, patchName: string) => void;
}

export function WhatsNewList({
	history,
	isLoading,
	activeData,
	onBundleClick,
	onAppClick,
	onPatchClick,
}: WhatsNewListProps) {
	const { visibleItems, loadMoreRef, hasMore } = useInfiniteScroll(
		history || [],
		WHATS_NEW_DAYS_PER_PAGE,
	);

	if (isLoading) {
		return (
			<div className="py-12 flex flex-col items-center justify-center text-center gap-3">
				<Loader2 className="size-8 animate-spin text-warning shrink-0" />
				<p className="text-sm font-medium text-foreground-muted">
					Loading What's New data...
				</p>
			</div>
		);
	}

	if (!history || history.length === 0) {
		return (
			<div className="py-12 flex flex-col items-center justify-center text-center text-foreground-subtle gap-2">
				<Sparkles className="size-8" />
				<p className="text-sm font-medium">No changes recorded.</p>
			</div>
		);
	}

	return (
		<div className="flex flex-col gap-6">
			{visibleItems.map((dayItem) => (
				<div key={dayItem.date} className="flex flex-col gap-3">
					<div className="sticky top-16 z-10 bg-background-translucent backdrop-blur-xs py-2 flex items-center gap-2 text-xs font-bold text-primary dark:text-secondary uppercase tracking-wider border-b border-divider mb-1.5">
						<Calendar className="size-3.5" />
						<span>{dayItem.date}</span>
					</div>

					<div className="flex flex-col gap-3">
						{Object.entries(dayItem.bundles || {}).map(([repo, bundleData]) => (
							<WhatsNewBundleCard
								key={repo}
								repo={repo}
								bundleData={bundleData}
								activeData={activeData}
								onBundleClick={onBundleClick}
								onAppClick={onAppClick}
								onPatchClick={onPatchClick}
							/>
						))}
					</div>
				</div>
			))}
			{hasMore && <div ref={loadMoreRef} className="h-px w-full mt-4" />}
		</div>
	);
}
