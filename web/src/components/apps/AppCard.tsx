import { memo } from "react";
import { GooglePlayButton } from "@/components/common/ActionButtons";
import { Badge } from "@/components/common/Badge";
import { AppAvatar } from "@/components/common/ItemAvatar";
import { PackageNameCopy } from "@/components/common/PackageNameCopy";
import {
	CATEGORY_UNIVERSAL,
	MIN_DISPLAY_INSTALLS,
	PACKAGE_UNIVERSAL,
} from "@/constants";
import { useCopy } from "@/hooks/useCopy";
import type { AppItem } from "@/types/data";
import { isNew } from "@/utils/formatters";

interface AppCardProps {
	appItem: AppItem;
	onClick: (packageName: string) => void;
}

export const AppCard = memo(function AppCard({
	appItem,
	onClick,
}: AppCardProps) {
	const { copiedText, copyToClipboard } = useCopy();

	const showGooglePlay =
		appItem.packageName !== PACKAGE_UNIVERSAL &&
		appItem.categorySlug !== CATEGORY_UNIVERSAL;

	return (
		<div className="relative isolate cursor-pointer p-5 md:p-4 flex flex-col gap-4 md:gap-3 border border-divider rounded-2xl transition-all hover:border-primary hover:shadow-md hover:-translate-y-0.5 h-full bg-card">
			<button
				type="button"
				aria-label={appItem.appName}
				onClick={() => onClick(appItem.packageName)}
				className="absolute inset-0 z-10 rounded-[inherit] cursor-pointer"
			/>
			<div className="flex items-center gap-3.5">
				<AppAvatar src={appItem.appIcon} size="lg" />

				<div className="flex-1 min-w-0 flex flex-col justify-center">
					<div className="text-base font-bold text-foreground mb-0.5 whitespace-normal wrap-break-word">
						<span>{appItem.appName}</span>
						{isNew(appItem.firstSeen) && (
							<Badge variant="new" className="ml-1.5" />
						)}
						{appItem.isPreRelease && (
							<Badge variant="prerelease" className="ml-1.5" />
						)}
						{showGooglePlay && appItem.minInstalls >= MIN_DISPLAY_INSTALLS && (
							<Badge
								variant="downloads"
								value={appItem.minInstalls}
								className="ml-1.5"
							/>
						)}
					</div>
					<PackageNameCopy
						className="relative z-20"
						packageName={appItem.packageName}
						copiedText={copiedText}
						copyToClipboard={copyToClipboard}
					/>
				</div>
			</div>

			<div className="flex-1">
				<p className="text-sm text-foreground-muted leading-relaxed line-clamp-2">
					{appItem.description}
				</p>
			</div>

			<div className="flex items-center justify-between gap-2 mt-auto w-full">
				<Badge variant="category" className="truncate max-w-[60%]">
					{appItem.category}
				</Badge>

				{showGooglePlay && (
					<GooglePlayButton
						packageName={appItem.packageName}
						className="relative z-20 ml-auto"
					/>
				)}
			</div>
		</div>
	);
});
