import { FlaskConical } from "lucide-react";
import { useState } from "react";
import type { VersionItem } from "@/features/catalog/types";

interface VersionChipProps {
	versionItem: VersionItem;
	chipKey: string;
	copiedText: string | null;
	copyToClipboard: (text: string, key?: string) => void;
}

function VersionChip({
	versionItem,
	chipKey,
	copiedText,
	copyToClipboard,
}: VersionChipProps) {
	const isCopied = copiedText === chipKey;

	return (
		<button
			type="button"
			onClick={(e) => {
				e.stopPropagation();
				copyToClipboard(versionItem.version, chipKey);
			}}
			className={`inline-grid grid-cols-1 items-center justify-center px-1 py-0 rounded-full text-xs font-normal transition-all cursor-pointer border ${
				isCopied
					? "bg-success/20 text-success border-success/40"
					: "bg-success/10 text-success border-success/30 hover:bg-success/20"
			}`}
			title={
				isCopied
					? "Copied!"
					: versionItem.isExperimental
						? "Experimental version (Click to copy)"
						: "Supported version (Click to copy)"
			}
		>
			<span
				className={`col-start-1 row-start-1 inline-flex items-center justify-center gap-0.5 ${isCopied ? "invisible" : "visible"}`}
			>
				{versionItem.isExperimental && (
					<FlaskConical className="size-2.5 text-warning shrink-0" />
				)}
				<span>{versionItem.version}</span>
			</span>
			<span
				className={`col-start-1 row-start-1 inline-flex items-center justify-center ${isCopied ? "visible" : "invisible"}`}
			>
				Copied!
			</span>
		</button>
	);
}

const ANY_VERSION_ITEMS: VersionItem[] = [{ version: "Any version" }];

interface SupportedVersionsProps {
	patchId: string;
	versions?: VersionItem[];
	copiedText: string | null;
	copyToClipboard: (text: string, key?: string) => void;
}

export function SupportedVersions({
	patchId,
	versions = [],
	copiedText,
	copyToClipboard,
}: SupportedVersionsProps) {
	const [showAll, setShowAll] = useState(false);
	const displayVersions = versions.length > 0 ? versions : ANY_VERSION_ITEMS;
	const hasMultiple = displayVersions.length > 1;

	return (
		<div
			className={`flex flex-wrap items-center gap-1 justify-end ml-auto ${showAll ? "max-w-full" : ""}`}
		>
			{displayVersions
				.slice(0, showAll ? undefined : 1)
				.map((versionItem, index) => (
					<VersionChip
						key={versionItem.version}
						versionItem={versionItem}
						chipKey={`${patchId}-version-${index}`}
						copiedText={copiedText}
						copyToClipboard={copyToClipboard}
					/>
				))}
			{(showAll || hasMultiple) && (
				<button
					type="button"
					onClick={(event) => {
						event.stopPropagation();
						setShowAll(!showAll);
					}}
					className="inline-flex items-center px-1.5 py-0 rounded-full text-xs font-normal bg-primary/10 text-primary border border-primary/30 hover:bg-primary/20 transition-all cursor-pointer shrink-0"
					title={
						showAll ? "Collapse version list" : "Show all supported versions"
					}
				>
					{showAll ? "Less" : `+${displayVersions.length - 1}`}
				</button>
			)}
		</div>
	);
}
