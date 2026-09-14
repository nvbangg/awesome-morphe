import { RowItem, VersionItem, PatchOption } from "@/types/data";
import { PACKAGE_UNIVERSAL } from "@/constants";
import { simplifyString } from "@/utils";

export interface TestBundleData {
  repoName: string;
  source: "github" | "gitlab";
  repoUrl: string;
  branches: Record<string, RowItem[]>;
  availableBranches: string[];
}

const BRANCHES_TO_TRY = ["main", "dev"];

function parseRepoInput(
  input: string,
): { owner: string; repo: string; source: "github" | "gitlab" } | null {
  try {
    const cleanInput = input.trim();
    if (!cleanInput.startsWith("http")) return null;

    const url = new URL(cleanInput);
    const parts = url.pathname.split("/").filter(Boolean);

    if (parts.length >= 2) {
      return {
        owner: parts[0],
        repo: parts[1].replace(/\.git$/, ""),
        source: url.hostname.includes("gitlab") ? "gitlab" : "github",
      };
    }
  } catch {
    // Return null if parsing fails
  }
  return null;
}

function getRawUrls(
  source: "github" | "gitlab",
  owner: string,
  repo: string,
  branch: string,
): string[] {
  const file = "patches-list.json";
  if (source === "gitlab") {
    const encodedProject = encodeURIComponent(`${owner}/${repo}`);
    const encodedFile = encodeURIComponent(file);
    return [
      `https://gitlab.com/api/v4/projects/${encodedProject}/repository/files/${encodedFile}/raw?ref=${branch}`,
      `https://gitlab.com/${owner}/${repo}/-/raw/${branch}/${file}`,
    ];
  }
  return [
    `https://raw.githubusercontent.com/${owner}/${repo}/${branch}/${file}`,
  ];
}

async function fetchFromUrls(urls: string[]): Promise<unknown | null> {
  for (const url of urls) {
    try {
      const response = await fetch(url, { cache: "no-store" });
      if (response.ok) {
        const text = await response.text();
        try {
          const json = JSON.parse(text);
          if (
            json &&
            typeof json === "object" &&
            !Array.isArray(json) &&
            Array.isArray((json as Record<string, unknown>).patches)
          ) {
            return json;
          }
        } catch {
          // Ignore invalid JSON responses
        }
      }
    } catch {
      // Continue to the next URL on fetch failure
    }
  }
  return null;
}

function parsePatchesToRows(
  data: unknown,
  bundleKey: string,
  mainPatchNames?: Set<string>,
  isDevBranch = false,
): RowItem[] {
  if (!data || typeof data !== "object" || Array.isArray(data)) return [];
  const dataObject = data as Record<string, unknown>;
  const patchesList = Array.isArray(dataObject.patches)
    ? (dataObject.patches as Array<Record<string, unknown>>)
    : [];

  const rows: RowItem[] = [];

  for (const patch of patchesList) {
    if (!patch || typeof patch !== "object" || !patch.name) continue;

    const patchName = String(patch.name);
    const patchDesc = patch.description ? String(patch.description) : "";
    const options: PatchOption[] = (patch.options as PatchOption[]) || [];
    const defaultVal = patch.default !== undefined ? patch.default : patch.use;
    const isDefault = defaultVal !== false;
    const isPatchPreRelease =
      isDevBranch && (!mainPatchNames || !mainPatchNames.has(patchName));

    const compatiblePackages: Array<{
      packageName: string;
      targets?: unknown[];
    }> = Array.isArray(patch.compatiblePackages)
      ? (patch.compatiblePackages as Array<{
          packageName: string;
          targets?: unknown[];
        }>)
      : patch.compatiblePackages && typeof patch.compatiblePackages === "object"
        ? Object.entries(patch.compatiblePackages).map(
            ([packageNameString, targets]) => ({
              packageName: packageNameString,
              targets: Array.isArray(targets) ? targets : [],
            }),
          )
        : [];

    if (compatiblePackages.length === 0) {
      rows.push({
        id: `${bundleKey}-no-pkg-${patchName}`,
        bundleKey,
        patchName,
        patchDesc,
        packageName: PACKAGE_UNIVERSAL,
        isPatchPreRelease,
        versions: [],
        searchPatchesText: simplifyString(`${patchName} ${patchDesc}`),
        options,
        default: isDefault,
      });
      continue;
    }

    for (const packageItem of compatiblePackages) {
      if (
        !packageItem ||
        typeof packageItem !== "object" ||
        !packageItem.packageName
      )
        continue;

      const packageName = packageItem.packageName;
      const versions: VersionItem[] = [];

      if (Array.isArray(packageItem.targets)) {
        for (const target of packageItem.targets) {
          if (typeof target === "string") {
            versions.push({ version: target, isExperimental: false });
          } else if (
            target &&
            typeof target === "object" &&
            "version" in target
          ) {
            const targetObject = target as {
              version: unknown;
              isExperimental?: unknown;
              experimental?: unknown;
            };
            if (typeof targetObject.version === "string") {
              versions.push({
                version: targetObject.version,
                isExperimental: Boolean(
                  targetObject.isExperimental || targetObject.experimental,
                ),
              });
            }
          }
        }
      }

      rows.push({
        id: `${bundleKey}-${packageName}-${patchName}`,
        bundleKey,
        patchName,
        patchDesc,
        packageName,
        isPatchPreRelease,
        versions,
        searchPatchesText: simplifyString(`${patchName} ${patchDesc}`),
        options,
        default: isDefault,
        firstSeen:
          typeof patch.firstSeen === "number" ? patch.firstSeen : undefined,
      });
    }
  }

  return rows;
}

export async function fetchTestBundle(input: string): Promise<TestBundleData> {
  const repoInfo = parseRepoInput(input);
  if (!repoInfo) {
    throw new Error("Invalid repository link format.");
  }

  const { owner, repo, source } = repoInfo;
  const repoName = `${owner}/${repo}`;
  const branchesData: Record<string, RowItem[]> = {};
  const availableBranches: string[] = [];

  let fetchSuccess = false;
  let mainPatchNames: Set<string> | undefined;

  for (const branch of BRANCHES_TO_TRY) {
    const urls = getRawUrls(source, owner, repo, branch);
    const data = await fetchFromUrls(urls);
    if (data) {
      fetchSuccess = true;
      const isDev = branch === "dev";
      const rows = parsePatchesToRows(
        data,
        `test-${repoName}-${branch}`,
        mainPatchNames,
        isDev,
      );
      if (rows.length > 0) {
        if (branch === "main") {
          mainPatchNames = new Set(rows.map((row) => row.patchName));
        }
        branchesData[branch] = rows;
        availableBranches.push(branch);
      }
    }
  }

  if (!fetchSuccess) {
    throw new Error("Could not find patches-list.json file in the repository.");
  }

  if (availableBranches.length === 0) {
    throw new Error(
      "Found patches-list.json, but no valid patches could be parsed.",
    );
  }

  return {
    repoName,
    source,
    repoUrl: `https://${source}.com/${repoName}`,
    branches: branchesData,
    availableBranches,
  };
}
