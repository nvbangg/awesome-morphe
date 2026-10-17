import { memo } from "react";
import { PatchButton } from "@/components/common/ActionButtons";
import { Badge } from "@/components/common/Badge";
import { AppAvatar } from "@/components/common/ItemAvatar";
import type { WhatsNewAppChange } from "@/types/data";

interface WhatsNewAppCardProps {
	packageName: string;
	appData: WhatsNewAppChange;
	appName: string;
	icon: string | null;
	isAppNew: boolean;
	onAppClick: (packageName: string) => void;
	onPatchClick: (packageName: string, patchName: string) => void;
}

export const WhatsNewAppCard = memo(function WhatsNewAppCard({
	packageName,
	appData,
	appName,
	icon,
	isAppNew,
	onAppClick,
	onPatchClick,
}: WhatsNewAppCardProps) {
	return (
		<div className="relative isolate flex flex-col gap-2 p-2.5 rounded-xl bg-card border border-divider transition-all hover:border-primary hover:shadow-md hover:-translate-y-0.5 cursor-pointer group">
			<button
				type="button"
				aria-label={appName}
				onClick={() => onAppClick(packageName)}
				className="absolute inset-0 z-10 rounded-[inherit] cursor-pointer"
			/>
			<div className="flex items-center gap-2 text-sm font-semibold text-foreground group-hover:text-primary transition-colors min-w-0">
				<AppAvatar src={icon} size="sm" />
				<span className="truncate">{appName}</span>
				{isAppNew && <Badge variant="new" />}
			</div>

			{appData.patches && appData.patches.length > 0 && (
				<div className="flex items-center gap-1.5 flex-wrap pl-0">
					{appData.patches.map((patchName) => (
						<PatchButton
							className="relative z-20"
							key={patchName}
							patchName={patchName}
							onClick={() => onPatchClick(packageName, patchName)}
						/>
					))}
				</div>
			)}
		</div>
	);
});
