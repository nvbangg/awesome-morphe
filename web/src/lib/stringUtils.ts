import { CATEGORY_UNIVERSAL } from "@/constants";

export function simplifyString(inputString: string | null | undefined): string {
	return inputString
		? inputString
				.normalize("NFKD")
				.replace(/[\u0300-\u036f]/g, "")
				.toLowerCase()
				.replace(/đ/g, "d")
				.replace(/[^\p{L}\p{N}]/gu, "")
		: "";
}

export function slugifyCategory(category: string): string {
	return category
		? category
				.toLowerCase()
				.replace(/[^a-z0-9]+/g, "-")
				.replace(/^-|-$/g, "")
		: CATEGORY_UNIVERSAL;
}
