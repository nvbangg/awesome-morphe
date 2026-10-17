import { useMemo, useState } from "react";
import { CustomModal, ModalBody } from "@/components/common/CustomModal";
import { ModalSearchBar } from "@/components/common/ModalSearchBar";
import { useCopy } from "@/hooks/useCopy";
import { useExpandedKeys } from "@/hooks/useExpandedKeys";
import { groupPatchesByApp, type TestBundleData } from "@/services";
import type { ActiveData, RowItem } from "@/types/data";
import { buildBundleUrls } from "@/utils";
import { BundleAppGroup } from "./BundleAppGroup";
import { TestBundleViewModalHeader } from "./TestBundleViewModalHeader";

interface TestBundleViewModalProps {
	isOpen: boolean;
	onClose: () => void;
	data: TestBundleData | null;
	activeData: ActiveData | null;
}

export function TestBundleViewModal({
	isOpen,
	onClose,
	data,
	activeData,
}: TestBundleViewModalProps) {
	const { copiedText, copyToClipboard } = useCopy();
	const [searchQuery, setSearchQuery] = useState("");
	const [selectedBranch, setSelectedBranch] = useState<string | null>(null);

	const branches = ["main", "dev"];

	const currentBranch =
		selectedBranch && data?.availableBranches.includes(selectedBranch)
			? selectedBranch
			: data?.availableBranches.includes("main")
				? "main"
				: data?.availableBranches[0] || "main";

	const handleClose = () => {
		setSearchQuery("");
		setSelectedBranch(null);
		onClose();
	};

	const currentRows: RowItem[] = useMemo(() => {
		if (!data || !currentBranch || !data.branches[currentBranch]) return [];
		return data.branches[currentBranch];
	}, [data, currentBranch]);

	const deepLink = useMemo(() => {
		if (!data) return "";
		return buildBundleUrls(data.source, data.repoName, currentBranch === "dev")
			.deepLink;
	}, [data, currentBranch]);

	const appGroups = useMemo(() => {
		if (!currentRows || !activeData) return [];
		return groupPatchesByApp(currentRows, activeData, searchQuery);
	}, [currentRows, activeData, searchQuery]);

	const appKeys = useMemo(
		() => appGroups.map((g) => g.packageName),
		[appGroups],
	);

	const { expandedKeys, toggleKey: toggleAppGroup } = useExpandedKeys(
		isOpen,
		appKeys,
		searchQuery,
	);

	const totalAppsCount = useMemo(() => {
		if (!currentRows) return 0;
		return new Set(currentRows.map((r) => r.packageName)).size;
	}, [currentRows]);

	if (!data) return null;

	return (
		<CustomModal isOpen={isOpen} onClose={handleClose}>
			<TestBundleViewModalHeader
				repoUrl={data.repoUrl}
				branches={branches}
				availableBranches={data.availableBranches}
				currentBranch={currentBranch}
				setCurrentBranch={setSelectedBranch}
				deepLink={deepLink}
				onClose={handleClose}
			/>

			<ModalBody>
				<ModalSearchBar
					value={searchQuery}
					onChange={setSearchQuery}
					count={totalAppsCount}
					label="app"
				/>

				<div className="flex flex-col gap-3 pr-1">
					{appGroups.length === 0 ? (
						<div className="py-12 text-center text-foreground-subtle text-sm font-medium">
							No apps found
						</div>
					) : (
						appGroups.map((group) => {
							const isExpanded = expandedKeys.has(group.packageName);
							return (
								<BundleAppGroup
									key={group.packageName}
									group={group}
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
