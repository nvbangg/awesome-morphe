import { memo } from "react";
import { AddToMorpheButton } from "@/components/common/ActionButtons";
import { Badge } from "@/components/common/Badge";
import { BundleAvatar } from "@/components/common/ItemAvatar";
import { RepoLink } from "@/components/common/RepoLink";
import type { Bundle } from "@/types/data";
import { formatDate, isNew } from "@/utils/formatters";

interface BundleCardProps {
	bundleItem: Bundle;
	onClick: (bundleKey: string) => void;
}

export const BundleCard = memo(function BundleCard({
	bundleItem,
	onClick,
}: BundleCardProps) {
	const { repoUrl, deepLink } = bundleItem;
	const formattedDate = formatDate(bundleItem.updatedAt);

	return (
		<div className="relative isolate cursor-pointer p-5 md:p-4 flex flex-col gap-4 md:gap-3 border border-divider rounded-2xl transition-all hover:border-primary hover:shadow-md hover:-translate-y-0.5 h-full bg-card">
			<button
				type="button"
				aria-label={bundleItem.name}
				onClick={() => onClick(bundleItem.key)}
				className="absolute inset-0 z-10 rounded-[inherit] cursor-pointer"
			/>
			<div className="flex items-center gap-3.5">
				<BundleAvatar src={bundleItem.avatarUrl} size="lg" />

				<div className="flex-1 min-w-0 flex flex-col justify-center">
					<div className="text-base font-bold text-foreground mb-0.5 whitespace-normal wrap-break-word">
						<span>{bundleItem.name}</span>
						{isNew(bundleItem.firstSeen) && (
							<Badge variant="new" className="ml-1.5" />
						)}
						{bundleItem.isPreRelease && (
							<Badge variant="prerelease" className="ml-1.5" />
						)}
						{bundleItem.isArchived && (
							<Badge variant="archived" className="ml-1.5" />
						)}
						{bundleItem.isUnofficial && (
							<Badge variant="unofficial" className="ml-1.5" />
						)}
						{bundleItem.stars > 0 && (
							<Badge
								variant="stars"
								value={bundleItem.stars}
								className="ml-1.5"
							/>
						)}
					</div>
					<RepoLink
						className="relative z-20"
						repo={bundleItem.repo}
						repoUrl={repoUrl}
						source={bundleItem.source}
					/>
				</div>
			</div>

			<div className="flex-1">
				<p className="text-sm text-foreground-muted leading-relaxed line-clamp-2">
					{bundleItem.repoDescription}
				</p>
			</div>

			<div className="flex items-center justify-between gap-2 mt-auto w-full">
				<div className="flex flex-wrap items-center gap-1.5 flex-1 min-w-0">
					{bundleItem.updatedAt > 0 && (
						<Badge
							className="relative z-20"
							variant="updated"
							href={bundleItem.changelogUrl}
						>
							{formattedDate}
						</Badge>
					)}
				</div>
				<AddToMorpheButton
					deepLink={deepLink}
					className="relative z-20 ml-auto"
				/>
			</div>
		</div>
	);
});
