import { ChevronDown } from "lucide-react";
import { memo } from "react";

interface ExpandChevronProps {
	isExpanded: boolean;
	className?: string;
}

export const ExpandChevron = memo(function ExpandChevron({
	isExpanded,
	className = "",
}: ExpandChevronProps) {
	return (
		<ChevronDown
			className={`size-4 text-foreground-muted transition-transform duration-200 shrink-0 ${
				isExpanded ? "rotate-180" : ""
			} ${className}`}
		/>
	);
});
