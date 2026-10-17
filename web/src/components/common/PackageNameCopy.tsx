import { Check, Copy } from "lucide-react";
import { memo } from "react";
import { PACKAGE_UNIVERSAL } from "@/constants";

interface PackageNameCopyProps {
	packageName?: string;
	copiedText?: string | null;
	copyToClipboard: (text: string, key?: string) => void;
	className?: string;
}

export const PackageNameCopy = memo(function PackageNameCopy({
	packageName,
	copiedText,
	copyToClipboard,
	className = "",
}: PackageNameCopyProps) {
	if (!packageName || packageName === PACKAGE_UNIVERSAL) return null;

	const isCopied = copiedText === packageName;

	return (
		<button
			type="button"
			onClick={(event) => {
				event.stopPropagation();
				copyToClipboard(packageName);
			}}
			className={`inline-flex items-center gap-1.5 mt-0.5 text-xs text-primary cursor-pointer max-w-full w-fit self-start ${className}`}
			title="Copy Package Name"
		>
			{isCopied ? (
				<Check className="size-3 text-success shrink-0" />
			) : (
				<Copy className="size-3 shrink-0 text-foreground-muted hover:text-primary" />
			)}
			<span className="break-all whitespace-normal text-primary font-medium dark:text-secondary min-w-0">
				{packageName}
			</span>
		</button>
	);
});
