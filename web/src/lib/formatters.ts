import { UI_NEW_BADGE_MS } from "@/constants";

const compactFormatter = new Intl.NumberFormat("en-US", {
	notation: "compact",
	maximumFractionDigits: 1,
});
const standardFormatter = new Intl.NumberFormat("en-US");

export function formatNumberCompact(count: number | undefined | null): string {
	if (!count) return "0";
	return `${compactFormatter.format(count)}+`;
}

export function formatStarCount(count: number | undefined | null): string {
	if (!count) return "0";
	return standardFormatter.format(count);
}

export function isNew(firstSeen: number | undefined | null): boolean {
	if (!firstSeen || firstSeen <= 0) return false;
	return Date.now() - firstSeen <= UI_NEW_BADGE_MS;
}

export function formatDate(timestamp: number | undefined | null): string {
	if (!timestamp || timestamp <= 0) return "";
	return new Date(timestamp).toLocaleDateString(undefined, {
		year: "numeric",
		month: "short",
		day: "numeric",
	});
}
