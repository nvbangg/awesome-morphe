import { usePathname } from "next/navigation";
import {
	createSerializer,
	parseAsString,
	parseAsStringLiteral,
	useQueryStates,
} from "nuqs";

const APP_SORT_PARSER = parseAsStringLiteral([
	"default",
	"new",
	"updated",
	"patches",
	"alpha",
]).withDefault("default");
const BUNDLE_SORT_PARSER = parseAsStringLiteral([
	"default",
	"new",
	"updated",
	"stars",
	"apps",
	"patches",
	"alpha",
]).withDefault("default");
const APP_CATEGORY_PARSER = parseAsString.withDefault("all");
const BUNDLE_CATEGORY_PARSER = parseAsStringLiteral([
	"all",
	"official",
	"unofficial",
]).withDefault("all");
const catalogParsers = {
	app: parseAsString.withDefault(""),
	github: parseAsString.withDefault(""),
	gitlab: parseAsString.withDefault(""),
	patch: parseAsString.withDefault(""),
	"test-bundle": parseAsString,
};
const serializeCatalogParams = createSerializer(catalogParsers);

export type CatalogTab = "apps" | "bundles" | "whats-new";

export function getBundleParams(bundleKey: string) {
	const [source, repo] = bundleKey.split(":");
	return {
		github: source === "github" ? repo : "",
		gitlab: source === "gitlab" ? repo : "",
		app: "",
		patch: "",
	};
}

export function useCatalogParams() {
	const isBundles = usePathname() === "/bundles";
	return useQueryStates(
		{
			...catalogParsers,
			sort: isBundles ? BUNDLE_SORT_PARSER : APP_SORT_PARSER,
			category: isBundles ? BUNDLE_CATEGORY_PARSER : APP_CATEGORY_PARSER,
		},
		{ history: "push" },
	);
}

export function setTestBundle(
	repository?: { source: "github" | "gitlab"; repoName: string } | null,
) {
	const target = repository
		? `${repository.source}:${repository.repoName}`
		: "";
	const href = serializeCatalogParams(
		`${window.location.pathname}${window.location.search}${window.location.hash}`,
		{
			...getBundleParams(target),
			"test-bundle": repository === null ? null : "",
		},
	).replace(/([?&]test-bundle)=(?=&|#|$)/, "$1");
	window.history.replaceState(null, "", href);
}
