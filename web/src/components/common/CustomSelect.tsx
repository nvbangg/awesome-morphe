import { useEffect, useRef, useState } from "react";
import { ExpandChevron } from "./ExpandChevron";

export interface CustomSelectProps {
	value: string;
	onChange: (value: string) => void;
	options: { key: string; label: string }[];
	icon: React.ElementType;
	ariaLabel: string;
	className?: string;
}

export function CustomSelect({
	value,
	onChange,
	options,
	icon: Icon,
	ariaLabel,
	className = "",
}: CustomSelectProps) {
	const [isOpen, setIsOpen] = useState(false);
	const containerRef = useRef<HTMLDivElement>(null);

	const selectedOption =
		options.find((option) => option.key === value) || options[0];

	useEffect(() => {
		if (!isOpen) return;

		const handleClickOutside = (event: MouseEvent) => {
			if (
				containerRef.current &&
				!containerRef.current.contains(event.target as Node)
			) {
				setIsOpen(false);
			}
		};

		const handleKeyDown = (event: KeyboardEvent) => {
			if (event.key === "Escape") {
				setIsOpen(false);
			}
		};

		document.addEventListener("mousedown", handleClickOutside);
		document.addEventListener("keydown", handleKeyDown);

		return () => {
			document.removeEventListener("mousedown", handleClickOutside);
			document.removeEventListener("keydown", handleKeyDown);
		};
	}, [isOpen]);

	return (
		<div ref={containerRef} className={`relative ${className}`}>
			<button
				type="button"
				onClick={() => setIsOpen((prev) => !prev)}
				aria-label={ariaLabel}
				aria-expanded={isOpen}
				className="w-full h-10 px-3 flex items-center justify-between border border-divider rounded-xl bg-background text-sm font-semibold text-foreground hover:bg-card transition-colors outline-none focus-visible:ring-2 focus-visible:ring-primary cursor-pointer"
			>
				<div className="flex items-center gap-2 overflow-hidden min-w-0">
					<Icon className="size-4 shrink-0 text-foreground-muted" />
					<span className="truncate">{selectedOption?.label || value}</span>
				</div>
				<ExpandChevron isExpanded={isOpen} className="ml-1" />
			</button>

			{isOpen && (
				<div className="absolute left-0 top-full mt-1.5 w-full max-h-[60vh] overflow-y-auto bg-background border border-divider rounded-xl shadow-xl z-50 p-1 flex flex-col divide-y divide-divider">
					{options.map((option) => {
						const isSelected = option.key === value;
						return (
							<button
								key={option.key}
								type="button"
								onClick={() => {
									onChange(option.key);
									setIsOpen(false);
								}}
								className={`px-3 py-2 text-sm font-medium rounded-lg text-left cursor-pointer transition-colors flex items-center justify-between whitespace-normal wrap-break-word ${
									isSelected
										? "bg-primary/10 text-primary font-semibold"
										: "text-foreground hover:bg-card"
								}`}
							>
								<span>{option.label}</span>
								{isSelected && (
									<span className="text-xs text-primary font-bold ml-2">✓</span>
								)}
							</button>
						);
					})}
				</div>
			)}
		</div>
	);
}
