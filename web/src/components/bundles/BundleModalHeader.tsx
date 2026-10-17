import { AddToMorpheButton } from "@/components/common/ActionButtons";
import { Badge } from "@/components/common/Badge";
import { CloseButton, ModalHeader } from "@/components/common/CustomModal";
import { BundleAvatar } from "@/components/common/ItemAvatar";
import { RepoLink } from "@/components/common/RepoLink";
import type { BundleMeta } from "@/utils/domainUtils";
import { isNew } from "@/utils/formatters";

interface BundleModalHeaderProps {
	bundleMeta: BundleMeta;
	formattedDate: string;
	onClose: () => void;
}

export function BundleModalHeader({
	bundleMeta,
	formattedDate,
	onClose,
}: BundleModalHeaderProps) {
	return (
		<ModalHeader>
			<div className="flex flex-row items-start justify-between gap-4 w-full">
				<div className="flex flex-row items-center gap-4 flex-1 min-w-0">
					<BundleAvatar src={bundleMeta.avatarUrl} size="lg" />
					<div className="flex flex-col min-w-0 justify-center">
						<div className="flex items-center gap-2 flex-wrap">
							<h2 className="text-xl font-bold tracking-tight text-foreground truncate">
								{bundleMeta.name}
							</h2>
							{isNew(bundleMeta.firstSeen) && <Badge variant="new" />}
							{bundleMeta.isPreRelease && <Badge variant="prerelease" />}
							{bundleMeta.isArchived && <Badge variant="archived" />}
							{bundleMeta.isUnofficial && <Badge variant="unofficial" />}
							{bundleMeta.stars > 0 && (
								<Badge variant="stars" value={bundleMeta.stars} />
							)}
						</div>
						<RepoLink
							repo={bundleMeta.repo}
							repoUrl={bundleMeta.repoUrl}
							source={bundleMeta.source}
							className="text-sm"
						/>
					</div>
				</div>

				<div className="hidden sm:flex items-center gap-2 shrink-0">
					{bundleMeta.updatedAt > 0 && (
						<Badge variant="updated" href={bundleMeta.changelogUrl}>
							{formattedDate}
						</Badge>
					)}
					{bundleMeta.deepLink && (
						<AddToMorpheButton deepLink={bundleMeta.deepLink} />
					)}
					<CloseButton onClose={onClose} />
				</div>

				<div className="sm:hidden shrink-0">
					<CloseButton onClose={onClose} />
				</div>
			</div>

			{bundleMeta.repoDescription && (
				<p className="text-sm text-foreground-muted leading-relaxed wrap-break-word">
					{bundleMeta.repoDescription}
				</p>
			)}

			<div className="flex sm:hidden items-center justify-between gap-3 mt-1 w-full">
				{bundleMeta.updatedAt > 0 && (
					<Badge variant="updated" href={bundleMeta.changelogUrl}>
						{formattedDate}
					</Badge>
				)}
				{bundleMeta.deepLink && (
					<AddToMorpheButton
						deepLink={bundleMeta.deepLink}
						className="shrink-0"
					/>
				)}
			</div>
		</ModalHeader>
	);
}
