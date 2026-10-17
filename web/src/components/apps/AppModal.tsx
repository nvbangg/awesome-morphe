import { useMemo } from "react";
import { CustomModal, ModalBody } from "@/components/common/CustomModal";
import { ModalSearchBar } from "@/components/common/ModalSearchBar";
import { useCopy } from "@/hooks/useCopy";
import { useExpandedKeys } from "@/hooks/useExpandedKeys";
import { getAppBundleGroups } from "@/services";
import type { ActiveData } from "@/types/data";
import { getAppMeta } from "@/utils/domainUtils";
import { isNew } from "@/utils/formatters";
import { AppBundleGroup } from "./AppBundleGroup";
import { AppModalHeader } from "./AppModalHeader";

interface AppModalProps {
	isOpen: boolean;
	onClose: () => void;
	packageName: string | null;
	activeData: ActiveData | null;
	searchQuery: string;
	onSearchChange: (searchValue: string) => void;
	isWhatsNew?: boolean;
}

export function AppModal({
	isOpen,
	onClose,
	packageName,
	activeData,
	searchQuery,
	onSearchChange,
	isWhatsNew,
}: AppModalProps) {
	const { copiedText, copyToClipboard } = useCopy();

	const appMeta = useMemo(() => {
		if (!packageName || !activeData) return null;
		return getAppMeta(packageName, activeData.namesMap);
	}, [packageName, activeData]);

	const bundleGroups = useMemo(() => {
		if (!packageName || !activeData) return [];
		return getAppBundleGroups(activeData, packageName, searchQuery, isWhatsNew);
	}, [packageName, activeData, searchQuery, isWhatsNew]);

	const bundleKeys = useMemo(
		() => bundleGroups.map((group) => group.bundleKey),
		[bundleGroups],
	);

	const { expandedKeys, toggleKey: toggleBundleGroup } = useExpandedKeys(
		isOpen,
		bundleKeys,
		searchQuery,
	);

	const totalBundlesCount = useMemo(() => {
		if (!packageName || !activeData) return 0;
		const rawPatches = activeData.appPatchesMap[packageName] || [];
		return new Set(
			rawPatches.map((patchItem) => patchItem.bundleKey.toLowerCase()),
		).size;
	}, [packageName, activeData]);

	if (!appMeta || !packageName) return null;

	return (
		<CustomModal isOpen={isOpen} onClose={onClose}>
			<AppModalHeader
				appMeta={appMeta}
				packageName={packageName}
				copiedText={copiedText}
				copyToClipboard={copyToClipboard}
				onClose={onClose}
			/>

			<ModalBody>
				<ModalSearchBar
					value={searchQuery}
					onChange={onSearchChange}
					count={totalBundlesCount}
					label="bundle"
				/>

				<div className="flex flex-col gap-3 pr-1">
					{bundleGroups.length === 0 ? (
						<div className="py-12 text-center text-foreground-subtle text-sm font-medium">
							No patches found
						</div>
					) : (
						bundleGroups.map((group) => {
							const isExpanded = expandedKeys.has(group.bundleKey);
							return (
								<AppBundleGroup
									key={group.bundleKey}
									group={group}
									displayPackage={packageName}
									isExpanded={isExpanded}
									toggleBundleGroup={toggleBundleGroup}
									copiedText={copiedText}
									copyToClipboard={copyToClipboard}
									isAppNew={isNew(appMeta.firstSeen)}
									isAppPreRelease={appMeta.isPreRelease}
								/>
							);
						})
					)}
				</div>
			</ModalBody>
		</CustomModal>
	);
}
