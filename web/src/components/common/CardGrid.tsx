import { SearchX } from "lucide-react";
import type { ReactNode, RefObject } from "react";

const SKELETON_COUNT = 6;
const SKELETON_KEYS = Array.from(
	{ length: SKELETON_COUNT },
	(_, skeletonId) => `skeleton-${skeletonId}`,
);

interface CardGridProps {
	children: ReactNode;
	hasMore?: boolean;
	loadMoreRef?: RefObject<HTMLDivElement | null>;
	className?: string;
}

export function CardGrid({
	children,
	hasMore,
	loadMoreRef,
	className = "",
}: CardGridProps) {
	return (
		<>
			<div
				className={`grid grid-cols-[repeat(auto-fill,minmax(min(300px,100%),1fr))] gap-5 my-6 ${className}`}
			>
				{children}
			</div>
			{hasMore && <div ref={loadMoreRef} className="h-px w-full" />}
		</>
	);
}

export function SkeletonGrid() {
	return (
		<CardGrid>
			{SKELETON_KEYS.map((skeletonId) => (
				<div
					key={skeletonId}
					className="p-4 border border-divider rounded-2xl bg-card flex flex-col gap-4"
				>
					<div className="flex gap-4">
						<div className="size-14 rounded-xl shrink-0 bg-divider animate-pulse" />
						<div className="flex flex-col gap-2 flex-1 justify-center">
							<div className="h-4 w-3/4 rounded bg-divider animate-pulse" />
							<div className="h-3 w-1/2 rounded bg-divider animate-pulse" />
						</div>
					</div>
					<div className="h-10 w-full rounded-xl bg-divider animate-pulse mt-auto" />
				</div>
			))}
		</CardGrid>
	);
}

interface EmptyStateProps {
	message: string;
}

export function EmptyState({ message }: EmptyStateProps) {
	return (
		<div className="flex flex-col items-center justify-center py-16 text-center border border-dashed border-divider rounded-2xl my-6">
			<SearchX className="size-10 text-foreground-subtle mb-3" />
			<p className="text-foreground-muted font-medium">{message}</p>
		</div>
	);
}
