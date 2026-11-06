import { useMemo } from "react";
import { ModalBody } from "@/components/common/CustomModal";
import { ModalSearchBar } from "@/components/common/ModalSearchBar";
import { getBundleAppGroups } from "@/features/catalog/search";
import type { ActiveData } from "@/features/catalog/types";
import { useCopy } from "@/hooks/useCopy";
import { useExpandedKeys } from "@/hooks/useExpandedKeys";
import { formatDate } from "@/lib/formatters";
import { BundleAppGroup } from "./BundleAppGroup";
import { BundleModalHeader } from "./BundleModalHeader";

interface BundleDetailProps {
	bundleKey: string;
	activeData: ActiveData;
	searchQuery: string;
	onSearchChange: (searchValue: string) => void;
	isWhatsNew?: boolean;
}

export function BundleDetail({
	bundleKey,
	activeData,
	searchQuery,
	onSearchChange,
	isWhatsNew,
}: BundleDetailProps) {
	const { copiedText, copyToClipboard } = useCopy();

	const bundleMeta = activeData.bundleMap[bundleKey.toLowerCase()];

	const formattedDate = formatDate(bundleMeta.updatedAt);

	const appGroups = useMemo(
		() => getBundleAppGroups(activeData, bundleKey, searchQuery, isWhatsNew),
		[bundleKey, activeData, searchQuery, isWhatsNew],
	);

	const appKeys = useMemo(
		() => appGroups.map((group) => group.packageName),
		[appGroups],
	);

	const { expandedKeys, toggleKey: toggleAppGroup } = useExpandedKeys(
		true,
		appKeys,
		searchQuery,
	);

	return (
		<>
			<BundleModalHeader
				bundleMeta={bundleMeta}
				formattedDate={formattedDate}
			/>

			<ModalBody>
				<ModalSearchBar
					value={searchQuery}
					onChange={onSearchChange}
					count={bundleMeta.appCount}
					label="app"
				/>

				<div className="flex flex-col gap-3 pr-1">
					{appGroups.length === 0 ? (
						<div className="py-12 text-center text-foreground-subtle text-sm font-medium">
							No patches found
						</div>
					) : (
						appGroups.map((group) => {
							const isExpanded = expandedKeys.has(group.packageName);
							return (
								<BundleAppGroup
									key={group.packageName}
									group={group}
									bundleMeta={bundleMeta}
									isExpanded={isExpanded}
									toggleAppGroup={toggleAppGroup}
									copiedText={copiedText}
									copyToClipboard={copyToClipboard}
								/>
							);
						})
					)}
				</div>
			</ModalBody>
		</>
	);
}
