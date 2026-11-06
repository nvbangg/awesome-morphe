import { afterEach, describe, expect, it, vi } from "vitest";
import {
	fetchTestBundle,
	parseRepository,
} from "../src/features/test-bundle/api";
import { ALPHA_PACKAGE, previewDev, previewMain } from "./catalog";

afterEach(() => vi.unstubAllGlobals());

describe("repository input and preview conversion", () => {
	it("normalizes GitHub URLs and preserves nested GitLab project paths", () => {
		expect(
			parseRepository(" https://github.com/Example/core.git/tree/dev ").repoUrl,
		).toBe("https://github.com/Example/core");
		expect(
			parseRepository("https://gitlab.com/group/subgroup/project/-/tree/dev"),
		).toMatchObject({ source: "gitlab", repoName: "group/subgroup/project" });
	});

	it("rejects unsupported hosts, credentials and incomplete repository URLs", () => {
		for (const input of [
			"http://github.com/owner/repo",
			"https://github.com.evil.test/owner/repo",
			"https://user:password@github.com/owner/repo",
			"https://github.com/owner",
			"invalid",
		])
			expect(() => parseRepository(input)).toThrow();
	});

	it("validates and normalizes main/dev artifacts while marking only new dev patches", async () => {
		vi.stubGlobal(
			"fetch",
			vi.fn(async (input: string) =>
				Response.json(input.includes("/main/") ? previewMain : previewDev),
			),
		);
		const data = await fetchTestBundle("https://github.com/example/preview");
		expect(data.availableBranches).toEqual(["main", "dev"]);
		expect(data.branches.main[0]).toMatchObject({
			packageName: ALPHA_PACKAGE,
			default: false,
			isPatchPreRelease: false,
		});
		expect(
			data.branches.dev.map((patch) => [
				patch.patchName,
				patch.isPatchPreRelease,
			]),
		).toEqual([
			["Unlock premium", false],
			["New controls", true],
		]);
		expect(data.branches.dev[1].versions).toEqual([
			{ version: "3.0", isExperimental: true },
		]);
	});

	it("rejects malformed external artifacts instead of treating them as an empty preview", async () => {
		vi.stubGlobal(
			"fetch",
			vi.fn(async () => Response.json({ patches: [{ name: 42 }] })),
		);
		await expect(
			fetchTestBundle("https://github.com/example/preview"),
		).rejects.toThrow("valid patches-list.json");
	});
});
