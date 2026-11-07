import {
	Archive,
	Calendar,
	Download,
	FlaskConical,
	Sparkles,
	Star,
	TriangleAlert,
} from "lucide-react";
import { MIN_DISPLAY_INSTALLS } from "@/constants";
import { formatNumberCompact, formatStarCount } from "@/lib/formatters";

type BadgeVariant =
	| "new"
	| "prerelease"
	| "archived"
	| "unofficial"
	| "off"
	| "stars"
	| "downloads"
	| "patches"
	| "count"
	| "category"
	| "updated";

interface BadgeProps {
	variant: BadgeVariant;
	value?: number;
	className?: string;
	title?: string;
	href?: string;
	children?: React.ReactNode;
}

const STATUS_BADGES = {
	new: { icon: Sparkles, label: "New", title: undefined },
	prerelease: { icon: FlaskConical, label: "Pre-release", title: undefined },
	archived: {
		icon: Archive,
		label: "Archived",
		title: "Repository is archived and read-only",
	},
	unofficial: {
		icon: TriangleAlert,
		label: "Unofficial",
		title: "Not included in Official Morphe Community Patches",
	},
};

export function Badge({
	variant,
	value,
	className = "",
	title,
	href,
	children,
}: BadgeProps) {
	const status = STATUS_BADGES[variant as keyof typeof STATUS_BADGES];
	if (status) {
		const Icon = status.icon;
		const colors =
			variant === "unofficial"
				? "text-success border-success/30"
				: "text-warning border-warning/30";
		return (
			<span
				className={`inline-flex items-center justify-center align-middle gap-1 px-1 py-0.5 text-xs font-semibold whitespace-nowrap border rounded-md shrink-0 ${colors} ${className}`}
				title={title || status.title}
			>
				<Icon
					className={`size-3 shrink-0 ${variant === "new" ? "fill-current" : ""} ${variant === "unofficial" ? "text-success" : "text-warning"}`}
				/>
				{status.label}
			</span>
		);
	}

	if (variant === "off") {
		return (
			<span
				className={`inline-flex items-center justify-center align-middle px-1 py-0.5 text-xs font-semibold whitespace-nowrap text-foreground-muted border border-divider rounded-md shrink-0 cursor-help ${className}`}
				title={title || "Disabled by default"}
			>
				off
			</span>
		);
	}

	if (variant === "stars" && value !== undefined && value > 0) {
		return (
			<span
				className={`inline-flex items-center justify-center align-middle gap-1 px-1 py-0.5 text-xs font-semibold whitespace-nowrap text-foreground-muted border border-divider rounded-md shrink-0 ${className}`}
				title={title}
			>
				<Star className="size-3 fill-current text-warning shrink-0" />
				{formatStarCount(value)}
			</span>
		);
	}

	if (
		variant === "downloads" &&
		value !== undefined &&
		value >= MIN_DISPLAY_INSTALLS
	) {
		return (
			<span
				className={`inline-flex items-center justify-center align-middle gap-1 px-1 py-0.5 text-xs font-semibold whitespace-nowrap text-foreground-muted border border-divider rounded-md shrink-0 ${className}`}
				title={title}
			>
				<Download className="size-3 text-warning shrink-0" />
				{formatNumberCompact(value)}
			</span>
		);
	}

	if (variant === "patches") {
		const content =
			value !== undefined
				? `${value} ${value === 1 ? "patch" : "patches"}`
				: children;
		return (
			<span
				className={`inline-flex items-center justify-center align-middle px-1.5 py-0.5 text-xs font-semibold whitespace-nowrap text-foreground-muted border border-divider rounded-full shrink-0 ${className}`}
				title={title}
			>
				{content}
			</span>
		);
	}

	if (variant === "count" || variant === "category") {
		return (
			<span
				className={`inline-flex items-center justify-center align-middle px-2 py-1 text-xs font-semibold whitespace-nowrap text-foreground-muted border border-divider rounded-full shrink-0 ${className}`}
				title={variant === "category" ? title || "Category" : title}
			>
				{children}
			</span>
		);
	}

	if (variant === "updated") {
		const Tag = href ? "a" : "span";
		return (
			<Tag
				href={href}
				target={href ? "_blank" : undefined}
				onClick={
					href ? (e: React.MouseEvent) => e.stopPropagation() : undefined
				}
				className={`inline-flex items-center justify-center align-middle gap-1 px-2 py-1 text-xs font-semibold whitespace-nowrap text-primary border border-primary/20 rounded-full shrink-0 ${href ? "hover:underline cursor-pointer" : ""} ${className}`}
				title={title || "View Release Changelog"}
			>
				<Calendar className="size-3.5 shrink-0" />
				{children}
			</Tag>
		);
	}

	return null;
}
