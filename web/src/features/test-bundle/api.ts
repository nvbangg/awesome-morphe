import { PACKAGE_UNIVERSAL } from "@/constants";
import type { RowItem } from "@/features/catalog/types";
import { simplifyString } from "@/lib/stringUtils";
import { type TestBundleArtifact, testBundleSchema } from "./schema";

const REPOSITORY_PATH_SEGMENTS = 2;
const BRANCHES = ["main", "dev"] as const;

export interface TestBundleData {
	repoName: string;
	source: "github" | "gitlab";
	repoUrl: string;
	branches: Record<string, RowItem[]>;
	availableBranches: string[];
}

export function parseRepository(input: string) {
	const url = new URL(input.trim());
	if (
		url.protocol !== "https:" ||
		url.username ||
		url.password ||
		url.port ||
		!["github.com", "gitlab.com"].includes(url.hostname)
	) {
		throw new Error("Enter an HTTPS GitHub or GitLab repository URL.");
	}
	const source = url.hostname === "github.com" ? "github" : "gitlab";
	const segments = url.pathname.split("/").filter(Boolean);
	const project =
		source === "github"
			? segments.slice(0, REPOSITORY_PATH_SEGMENTS)
			: segments.slice(
					0,
					segments.indexOf("-") < 0 ? undefined : segments.indexOf("-"),
				);
	if (project.length < REPOSITORY_PATH_SEGMENTS)
		throw new Error("Invalid repository link format.");
	const repoName = project.join("/").replace(/\.git$/, "");
	return {
		source,
		repoName,
		repoUrl: `https://${url.hostname}/${repoName}`,
	} as const;
}

async function fetchBranch(
	repository: ReturnType<typeof parseRepository>,
	branch: string,
	signal?: AbortSignal,
) {
	const { source, repoName } = repository;
	const urls =
		source === "github"
			? [
					`https://raw.githubusercontent.com/${repoName}/${branch}/patches-list.json`,
				]
			: [
					`https://gitlab.com/api/v4/projects/${encodeURIComponent(repoName)}/repository/files/patches-list.json/raw?ref=${branch}`,
					`https://gitlab.com/${repoName}/-/raw/${branch}/patches-list.json`,
				];
	for (const url of urls) {
		try {
			const response = await fetch(url, { cache: "no-store", signal });
			if (!response.ok) continue;
			const parsed = testBundleSchema.safeParse(await response.json());
			if (parsed.success) return parsed.data;
		} catch (error) {
			if (signal?.aborted) throw error;
		}
	}
	return null;
}

function buildTestRows(
	data: TestBundleArtifact,
	bundleKey: string,
	mainPatchNames?: Set<string>,
	isDev = false,
): RowItem[] {
	return data.patches.flatMap((patch) => {
		const packages = patch.compatiblePackages.length
			? patch.compatiblePackages
			: [{ packageName: PACKAGE_UNIVERSAL, targets: [] }];
		return packages.map(({ packageName, targets }) => ({
			id: `${bundleKey}-${packageName}-${patch.name}`,
			bundleKey,
			patchName: patch.name,
			patchDesc: patch.description,
			packageName,
			isPatchPreRelease: isDev && !mainPatchNames?.has(patch.name),
			versions: targets,
			searchPatchesText: simplifyString(`${patch.name} ${patch.description}`),
			options: patch.options,
			default: patch.default,
			firstSeen: patch.firstSeen,
		}));
	});
}

export async function fetchTestBundle(
	input: string,
	signal?: AbortSignal,
): Promise<TestBundleData> {
	const repository = parseRepository(input);
	const artifacts = await Promise.all(
		BRANCHES.map((branch) => fetchBranch(repository, branch, signal)),
	);
	if (!artifacts.some(Boolean))
		throw new Error(
			"Could not find valid patches-list.json data in the repository.",
		);
	const mainNames = new Set(artifacts[0]?.patches.map((patch) => patch.name));
	const branches: Record<string, RowItem[]> = {};
	for (const [index, branch] of BRANCHES.entries()) {
		const artifact = artifacts[index];
		if (artifact?.patches.length)
			branches[branch] = buildTestRows(
				artifact,
				`test-${repository.repoName}-${branch}`,
				mainNames,
				branch === "dev",
			);
	}
	const availableBranches = Object.keys(branches);
	if (!availableBranches.length)
		throw new Error(
			"Found patches-list.json, but no valid patches could be parsed.",
		);
	return { ...repository, branches, availableBranches };
}
