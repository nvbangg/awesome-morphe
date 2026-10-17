import { Search, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

interface SearchInputProps {
	value: string;
	onChange: (value: string) => void;
	placeholder?: string;
	id?: string;
	className?: string;
	debounceMs?: number;
}

export function SearchInput({
	value,
	onChange,
	placeholder = "Search…",
	id,
	className = "",
	debounceMs = 150,
}: SearchInputProps) {
	const [localValue, setLocalValue] = useState(value);
	const [prevValue, setPrevValue] = useState(value);
	const inputRef = useRef<HTMLInputElement>(null);

	if (value !== prevValue) {
		setPrevValue(value);
		setLocalValue(value);
	}

	useEffect(() => {
		const timer = setTimeout(() => {
			if (localValue !== value) {
				onChange(localValue);
			}
		}, debounceMs);
		return () => clearTimeout(timer);
	}, [localValue, value, onChange, debounceMs]);

	const handleClear = () => {
		setLocalValue("");
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
				value={localValue}
				onChange={(event) => setLocalValue(event.target.value)}
				onKeyDown={(event) => {
					if (event.key === "Enter") {
						if (localValue !== value) {
							onChange(localValue);
						}
						(event.target as HTMLInputElement)?.blur();
					}
				}}
				enterKeyHint="search"
				placeholder={placeholder}
				className="w-full h-10 pl-10 pr-9 bg-background border border-divider rounded-xl text-sm font-medium text-foreground placeholder:text-foreground-subtle placeholder:select-none outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all"
			/>

			{localValue && (
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
