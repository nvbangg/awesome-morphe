import { useMemo } from "react";
import { ModalBody } from "@/components/common/CustomModal";
import { ModalSearchBar } from "@/components/common/ModalSearchBar";
import { getAppMeta } from "@/features/catalog/helpers";
import { getAppBundleGroups } from "@/features/catalog/search";
import type { ActiveData } from "@/features/catalog/types";
import { useCopy } from "@/hooks/useCopy";
import { useExpandedKeys } from "@/hooks/useExpandedKeys";
import { isNew } from "@/lib/formatters";
import { AppBundleGroup } from "./AppBundleGroup";
import { AppModalHeader } from "./AppModalHeader";

interface AppDetailProps {
	packageName: string;
	activeData: ActiveData;
	searchQuery: string;
	onSearchChange: (searchValue: string) => void;
	isWhatsNew?: boolean;
}

export function AppDetail({
	packageName,
	activeData,
	searchQuery,
	onSearchChange,
	isWhatsNew,
}: AppDetailProps) {
	const { copiedText, copyToClipboard } = useCopy();

	const appMeta = getAppMeta(packageName, activeData.namesMap);

	const bundleGroups = useMemo(
		() => getAppBundleGroups(activeData, packageName, searchQuery, isWhatsNew),
		[packageName, activeData, searchQuery, isWhatsNew],
	);

	const bundleKeys = useMemo(
		() => bundleGroups.map((group) => group.bundleKey),
		[bundleGroups],
	);

	const { expandedKeys, toggleKey: toggleBundleGroup } = useExpandedKeys(
		true,
		bundleKeys,
		searchQuery,
	);

	const totalBundlesCount = useMemo(() => {
		const rawPatches = activeData.appPatchesMap[packageName] || [];
		return new Set(
			rawPatches.map((patchItem) => patchItem.bundleKey.toLowerCase()),
		).size;
	}, [packageName, activeData]);

	return (
		<>
			<AppModalHeader
				appMeta={appMeta}
				packageName={packageName}
				copiedText={copiedText}
				copyToClipboard={copyToClipboard}
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
		</>
	);
}
