import { Select } from "@base-ui/react/select";
import { ChevronDown } from "lucide-react";

interface CustomSelectProps {
	value: string;
	onChange: (value: string) => void;
	options: { value: string; label: string }[];
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
	return (
		<Select.Root
			items={options}
			value={value}
			modal={false}
			onValueChange={(nextValue) => {
				if (nextValue !== null) onChange(nextValue);
			}}
		>
			<div className={`relative ${className}`}>
				<Select.Trigger
					aria-label={ariaLabel}
					className="w-full h-10 px-3 flex items-center justify-between border border-divider rounded-xl bg-background text-sm font-semibold text-foreground hover:bg-card transition-colors outline-none focus-visible:ring-2 focus-visible:ring-primary cursor-pointer"
				>
					<div className="flex items-center gap-2 overflow-hidden min-w-0">
						<Icon className="size-4 shrink-0 text-foreground-muted" />
						<Select.Value className="truncate" />
					</div>
					<Select.Icon
						render={<ChevronDown />}
						className="size-4 text-foreground-muted transition-transform duration-200 shrink-0 data-popup-open:rotate-180 ml-1"
					>
						{null}
					</Select.Icon>
				</Select.Trigger>
			</div>
			<Select.Portal>
				<Select.Positioner
					align="start"
					alignItemWithTrigger={false}
					sideOffset={6}
					className="z-50"
				>
					<Select.Popup className="w-(--anchor-width) max-h-[min(60vh,var(--available-height))] overflow-y-auto bg-background border border-divider rounded-xl shadow-xl p-1 flex flex-col divide-y divide-divider outline-none">
						{options.map((option) => (
							<Select.Item
								key={option.value}
								value={option.value}
								className={`px-3 py-2 text-sm font-medium rounded-lg text-left cursor-pointer transition-colors flex items-center justify-between whitespace-normal wrap-break-word outline-none ${option.value === value ? "bg-primary/10 text-primary font-semibold" : "text-foreground hover:bg-card data-highlighted:bg-card"}`}
							>
								<Select.ItemText>{option.label}</Select.ItemText>
								<Select.ItemIndicator className="text-xs text-primary font-bold ml-2">
									✓
								</Select.ItemIndicator>
							</Select.Item>
						))}
					</Select.Popup>
				</Select.Positioner>
			</Select.Portal>
		</Select.Root>
	);
}
