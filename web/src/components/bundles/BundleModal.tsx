import { useMemo } from "react";
import { CustomModal, ModalBody } from "@/components/common/CustomModal";
import { ModalSearchBar } from "@/components/common/ModalSearchBar";
import { useCopy } from "@/hooks/useCopy";
import { useExpandedKeys } from "@/hooks/useExpandedKeys";
import { getBundleAppGroups } from "@/services";
import type { ActiveData } from "@/types/data";
import { getBundleMeta } from "@/utils/domainUtils";
import { formatDate } from "@/utils/formatters";
import { BundleAppGroup } from "./BundleAppGroup";
import { BundleModalHeader } from "./BundleModalHeader";

interface BundleModalProps {
	isOpen: boolean;
	onClose: () => void;
	bundleKey: string | null;
	activeData: ActiveData | null;
	searchQuery: string;
	onSearchChange: (searchValue: string) => void;
	isWhatsNew?: boolean;
}

export function BundleModal({
	isOpen,
	onClose,
	bundleKey,
	activeData,
	searchQuery,
	onSearchChange,
	isWhatsNew,
}: BundleModalProps) {
	const { copiedText, copyToClipboard } = useCopy();

	const bundleMeta = useMemo(() => {
		if (!bundleKey || !activeData) return null;
		return getBundleMeta(bundleKey, activeData.bundleMap);
	}, [bundleKey, activeData]);

	const formattedDate = formatDate(bundleMeta?.updatedAt);

	const appGroups = useMemo(() => {
		if (!bundleKey || !activeData) return [];
		return getBundleAppGroups(activeData, bundleKey, searchQuery, isWhatsNew);
	}, [bundleKey, activeData, searchQuery, isWhatsNew]);

	const appKeys = useMemo(
		() => appGroups.map((group) => group.packageName),
		[appGroups],
	);

	const { expandedKeys, toggleKey: toggleAppGroup } = useExpandedKeys(
		isOpen,
		appKeys,
		searchQuery,
	);

	if (!bundleMeta || !bundleKey) return null;

	return (
		<CustomModal isOpen={isOpen} onClose={onClose}>
			<BundleModalHeader
				bundleMeta={bundleMeta}
				formattedDate={formattedDate}
				onClose={onClose}
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
		</CustomModal>
	);
}
