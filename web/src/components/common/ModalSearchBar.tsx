import { memo } from "react";
import { Badge } from "@/components/common/Badge";
import { SearchInput } from "@/components/common/SearchInput";

interface ModalSearchBarProps {
	value: string;
	onChange: (value: string) => void;
	count: number;
	label: string;
	placeholder?: string;
}

export const ModalSearchBar = memo(function ModalSearchBar({
	value,
	onChange,
	count,
	label,
	placeholder = "Search patches…",
}: ModalSearchBarProps) {
	const pluralSuffix = count === 1 ? "" : label.endsWith("s") ? "es" : "s";
	const displayLabel = `${count} ${label}${pluralSuffix}`;

	return (
		<div className="flex items-center gap-3">
			<SearchInput
				id="patch-search"
				placeholder={placeholder}
				value={value}
				onChange={onChange}
				className="flex-1"
			/>
			<Badge variant="count">{displayLabel}</Badge>
		</div>
	);
});
