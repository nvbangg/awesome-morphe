import { AddToMorpheButton } from "@/components/common/ActionButtons";
import { Badge } from "@/components/common/Badge";
import { ExpandChevron } from "@/components/common/ExpandChevron";
import { BundleAvatar } from "@/components/common/ItemAvatar";
import { PatchItemRow } from "@/components/common/PatchItemRow";
import { RepoLink } from "@/components/common/RepoLink";
import type { BundleGroupData } from "@/services/queryService";
import { isAllPatchesPreRelease } from "@/utils/domainUtils";
import { formatDate, isNew } from "@/utils/formatters";

interface AppBundleGroupProps {
	group: BundleGroupData;
	displayPackage: string | null;
	isExpanded: boolean;
	toggleBundleGroup: (bundleKey: string) => void;
	copiedText: string | null;
	copyToClipboard: (text: string, key?: string) => void;
	isAppNew?: boolean;
	isAppPreRelease?: boolean;
}

export function AppBundleGroup({
	group,
	displayPackage,
	isExpanded,
	toggleBundleGroup,
	copiedText,
	copyToClipboard,
	isAppNew,
	isAppPreRelease,
}: AppBundleGroupProps) {
	const isBundleRowPreRelease = isAllPatchesPreRelease(group.patches);

	const showBundleNewBadge =
		!isAppNew &&
		Boolean(
			displayPackage && isNew(group.bundleMeta.appFirstSeen?.[displayPackage]),
		);
	const showBundlePreReleaseBadge = !isAppPreRelease && isBundleRowPreRelease;
	const hidePatchPreReleaseBadge = isAppPreRelease || isBundleRowPreRelease;
	const hidePatchNewBadge = isAppNew || showBundleNewBadge;

	const patchBadge = <Badge variant="patches" value={group.totalPatchCount} />;

	const updatedAt =
		(displayPackage && group.bundleMeta.appUpdates?.[displayPackage]) ||
		group.bundleMeta.updatedAt;

	const dateBadge = updatedAt > 0 && (
		<Badge
			className="relative z-20"
			variant="updated"
			href={group.bundleMeta.changelogUrl}
		>
			{formatDate(updatedAt)}
		</Badge>
	);

	return (
		<div className="border border-divider rounded-xl bg-card flex flex-col">
			<div
				className={`relative isolate flex flex-col gap-2 px-4 py-3 bg-card cursor-pointer rounded-t-xl ${isExpanded ? "border-b border-divider shadow-sm" : "rounded-b-xl"}`}
			>
				<button
					type="button"
					aria-label={group.bundleMeta.name}
					aria-expanded={isExpanded}
					onClick={() => toggleBundleGroup(group.bundleKey)}
					className="absolute inset-0 z-10 rounded-[inherit] cursor-pointer"
				/>
				<div className="flex items-center justify-between gap-3 w-full">
					<BundleAvatar src={group.bundleMeta.avatarUrl} />

					<div className="flex-1 min-w-0 flex flex-col justify-center">
						<div className="flex items-center gap-2 flex-wrap min-w-0">
							<div className="font-bold text-foreground text-sm truncate">
								{group.bundleMeta.name}
							</div>
							{showBundleNewBadge && <Badge variant="new" />}
							{showBundlePreReleaseBadge && <Badge variant="prerelease" />}
							{group.bundleMeta.isArchived && <Badge variant="archived" />}
							{group.bundleMeta.isUnofficial && <Badge variant="unofficial" />}
							{group.bundleMeta.stars > 0 && (
								<Badge variant="stars" value={group.bundleMeta.stars} />
							)}
						</div>

						<RepoLink
							className="relative z-20"
							repo={group.bundleMeta.repo}
							repoUrl={group.bundleMeta.repoUrl}
							source={group.bundleMeta.source}
						/>
					</div>

					<div className="flex items-center gap-2 shrink-0">
						{group.bundleMeta.deepLink ? (
							<div className="hidden sm:flex items-center gap-2">
								{patchBadge}
								{dateBadge}
								<AddToMorpheButton
									className="relative z-20"
									deepLink={group.bundleMeta.deepLink}
									size="sm"
								/>
							</div>
						) : (
							<>
								{patchBadge}
								{dateBadge}
							</>
						)}
						<ExpandChevron
							isExpanded={isExpanded}
							className="hidden sm:inline-flex"
						/>
					</div>
				</div>

				{group.bundleMeta.deepLink && (
					<div className="sm:hidden flex items-center justify-between gap-2 pt-1">
						<div className="flex items-center gap-1.5 flex-wrap min-w-0">
							{patchBadge}
							{dateBadge}
						</div>
						<AddToMorpheButton
							className="relative z-20"
							deepLink={group.bundleMeta.deepLink}
							size="sm"
						/>
					</div>
				)}
			</div>

			{isExpanded && (
				<div className="flex flex-col max-h-[50dvh] overflow-y-auto pr-1">
					{group.patches.map((patchItem) => (
						<PatchItemRow
							key={patchItem.id}
							patchItem={patchItem}
							copiedText={copiedText}
							copyToClipboard={copyToClipboard}
							hidePreReleaseBadge={hidePatchPreReleaseBadge}
							hideNewBadge={hidePatchNewBadge}
						/>
					))}
				</div>
			)}
		</div>
	);
}
