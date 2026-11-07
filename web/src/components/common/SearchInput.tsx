import { Search, X } from "lucide-react";
import { useRef } from "react";

interface SearchInputProps {
	value: string;
	onChange: (value: string) => void;
	placeholder?: string;
	id?: string;
	className?: string;
}

export function SearchInput({
	value,
	onChange,
	placeholder = "Search…",
	id,
	className = "",
}: SearchInputProps) {
	const inputRef = useRef<HTMLInputElement>(null);

	const handleClear = () => {
		onChange("");
		inputRef.current?.focus();
	};

	return (
		<div className={`relative flex items-center ${className}`}>
			<div className="absolute left-3.5 top-1/2 -translate-y-1/2 z-10 text-foreground-subtle pointer-events-none">
				<Search className="size-4" />
			</div>

			<input
				ref={inputRef}
				type="text"
				id={id}
				value={value}
				onChange={(event) => onChange(event.target.value)}
				onKeyDown={(event) => {
					if (event.key === "Enter") {
						event.currentTarget.blur();
					}
				}}
				enterKeyHint="search"
				placeholder={placeholder}
				className="w-full h-10 pl-10 pr-9 bg-background border border-divider rounded-xl text-sm font-medium text-foreground placeholder:text-foreground-subtle placeholder:select-none outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all"
			/>

			{value && (
				<button
					type="button"
					onClick={handleClear}
					aria-label="Clear search"
					className="absolute right-2.5 top-1/2 -translate-y-1/2 z-10 size-5 rounded-full flex items-center justify-center border-none cursor-pointer transition-colors bg-card text-foreground-muted hover:text-foreground"
				>
					<X className="size-3.5" />
				</button>
			)}
		</div>
	);
}
