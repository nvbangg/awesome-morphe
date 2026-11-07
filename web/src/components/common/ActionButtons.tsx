import { Play, Plus } from "lucide-react";

type ButtonSize = "sm" | "md";

const LINK_BUTTON_CLASS =
	"inline-flex items-center justify-center rounded-lg font-semibold whitespace-nowrap select-none transition-all bg-primary-gradient text-background dark:text-foreground hover:opacity-90 shadow-xs";
const LINK_BUTTON_SIZES = {
	sm: "h-6 px-2 text-xs gap-1",
	md: "h-7 px-2.5 text-xs gap-1.5",
};

interface AddToMorpheButtonProps {
	deepLink?: string;
	size?: ButtonSize;
	className?: string;
}

export function AddToMorpheButton({
	deepLink,
	size = "md",
	className = "",
}: AddToMorpheButtonProps) {
	if (!deepLink) return null;

	const isSmall = size === "sm";

	return (
		<a
			href={deepLink}
			target="_blank"
			onClick={(e) => e.stopPropagation()}
			className={`${LINK_BUTTON_CLASS} ${LINK_BUTTON_SIZES[size]} ${className}`}
			rel="noopener"
		>
			<Plus className={isSmall ? "size-3 shrink-0" : "size-3.5 shrink-0"} />
			Add to Morphe
		</a>
	);
}

interface GooglePlayButtonProps {
	packageName?: string;
	size?: ButtonSize;
	className?: string;
}

export function GooglePlayButton({
	packageName,
	size = "md",
	className = "",
}: GooglePlayButtonProps) {
	if (!packageName) return null;

	const isSmall = size === "sm";

	return (
		<a
			href={`https://play.google.com/store/apps/details?id=${packageName}`}
			target="_blank"
			onClick={(e) => e.stopPropagation()}
			className={`${LINK_BUTTON_CLASS} ${LINK_BUTTON_SIZES[size]} ${className}`}
			rel="noopener"
		>
			<Play
				className={
					isSmall
						? "size-3 fill-current shrink-0"
						: "size-3.5 fill-current shrink-0"
				}
			/>
			Google Play
		</a>
	);
}

interface PatchButtonProps {
	patchName: string;
	onClick: () => void;
	className?: string;
}

export function PatchButton({
	patchName,
	onClick,
	className = "",
}: PatchButtonProps) {
	return (
		<button
			type="button"
			onClick={(e) => {
				e.stopPropagation();
				onClick();
			}}
			className={`inline-flex items-center justify-center font-semibold rounded-full text-xs px-2.5 py-1 bg-card hover:bg-divider text-foreground-muted hover:text-foreground transition-all cursor-pointer outline-none shrink-0 max-w-full truncate border border-divider active:scale-95 ${className}`}
		>
			<span className="truncate">{patchName}</span>
		</button>
	);
}
