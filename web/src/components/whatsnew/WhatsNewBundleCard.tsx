import { memo } from "react";
import { Badge } from "@/components/common/Badge";
import { BundleAvatar } from "@/components/common/ItemAvatar";
import type { ActiveData, WhatsNewBundleChange } from "@/types/data";
import { getAppMeta } from "@/utils";
import { WhatsNewAppCard } from "./WhatsNewAppCard";

interface WhatsNewBundleCardProps {
	repo: string;
	bundleData: WhatsNewBundleChange;
	activeData: ActiveData | null;
	onBundleClick: (bundleKey: string) => void;
	onAppClick: (packageName: string) => void;
	onPatchClick: (packageName: string, patchName: string) => void;
}

export const WhatsNewBundleCard = memo(function WhatsNewBundleCard({
	repo,
	bundleData,
	activeData,
	onBundleClick,
	onAppClick,
	onPatchClick,
}: WhatsNewBundleCardProps) {
	const bundle = activeData?.bundleMap[repo.toLowerCase()];
	if (activeData && !bundle) return null;

	const fullBundleKey = bundle ? bundle.key : repo;
	const displayName = bundle?.name || repo.split("/")[1] || repo;
	const isBundleNew = !!bundleData.isNew;

	const validAppEntries = bundleData.apps
		? Object.entries(bundleData.apps).filter(
				([packageName]) =>
					!activeData || !!activeData.appPatchesMap[packageName],
			)
		: [];

	if (!isBundleNew && validAppEntries.length === 0) return null;

	return (
		<div className="border border-divider rounded-2xl overflow-hidden shadow-2xs bg-background">
			<button
				type="button"
				onClick={() => onBundleClick(fullBundleKey)}
				className="w-full flex items-center justify-between gap-3 p-3 bg-primary/5 dark:bg-primary/10 border-b border-primary/10 dark:border-primary/20 text-left outline-none transition-colors group cursor-pointer"
				title="Open bundle details"
			>
				<div className="flex items-center gap-2.5 min-w-0">
					<BundleAvatar src={bundle?.avatarUrl} size="md" />
					<div className="flex flex-col min-w-0">
						<div className="flex items-center gap-2 text-base font-semibold text-foreground group-hover:text-primary transition-colors min-w-0">
							<span className="truncate">{displayName}</span>
							{isBundleNew && <Badge variant="new" />}
						</div>
						<span className="text-xs font-medium text-primary dark:text-secondary truncate">
							{repo}
						</span>
					</div>
				</div>
			</button>

			{validAppEntries.length > 0 && (
				<div className="p-2.5 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2.5">
					{validAppEntries.map(([packageName, appData]) => {
						const meta = activeData
							? getAppMeta(packageName, activeData.namesMap)
							: null;
						const icon = meta?.appIcon || null;
						const appName = appData.appName || meta?.appName || packageName;
						const isAppNew = !isBundleNew && !!appData.isNew;

						return (
							<WhatsNewAppCard
								key={packageName}
								packageName={packageName}
								appData={appData}
								appName={appName}
								icon={icon}
								isAppNew={isAppNew}
								onAppClick={onAppClick}
								onPatchClick={onPatchClick}
							/>
						);
					})}
				</div>
			)}
		</div>
	);
});
