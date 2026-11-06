import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import {
	ALPHA_PACKAGE,
	CORE_KEY,
	catalog,
	previewDev,
	previewMain,
} from "../tests/catalog";

test.beforeEach(async ({ page, baseURL }) => {
	await page.route("**/*", (route) => {
		const url = new URL(route.request().url());
		if (url.origin === baseURL) {
			if (url.pathname === "/bundles.json")
				return route.fulfill({ json: catalog });
			if (url.pathname === "/whats-new.json")
				return route.fulfill({
					json: [
						{
							date: "2026-01-15",
							bundles: {
								"https://github.com/Example/core": {
									apps: { [ALPHA_PACKAGE]: { patches: ["Playback options"] } },
								},
							},
						},
					],
				});
			return route.continue();
		}
		if (
			url.hostname === "raw.githubusercontent.com" &&
			url.pathname.startsWith("/example/preview/")
		)
			return route.fulfill({
				json: url.pathname.includes("/main/") ? previewMain : previewDev,
			});
		return route.abort();
	});
});

test("navigates between tabs and recovers from a 404", async ({ page }) => {
	await page.goto("/apps");
	await expect(
		page.getByRole("button", { name: "Alpha Player", exact: true }),
	).toBeVisible();
	await page.getByRole("link", { name: "Bundles", exact: true }).click();
	await expect(
		page.getByRole("button", { name: "Core patches", exact: true }),
	).toBeVisible();
	await page.getByRole("link", { name: "What's New", exact: true }).click();
	await expect(
		page.getByRole("button", { name: "Playback options", exact: true }),
	).toBeVisible();
	const response = await page.goto("/missing-page");
	expect(response?.status()).toBe(404);
	await expect(
		page.getByRole("heading", { name: "404", exact: true }),
	).toBeVisible();
	await page.getByRole("link", { name: "Apps", exact: true }).click();
	await expect(
		page.getByRole("button", { name: "Alpha Player", exact: true }),
	).toBeVisible();
	await expect(page).toHaveURL("/");
});

test("preserves filters and search through popup close and Back/Forward", async ({
	page,
}) => {
	const background = "/?sort=updated&category=video-players-editors";
	await page.goto(background);
	const search = page.locator("#search-input");
	await search.fill("alpha");
	await page.getByRole("button", { name: "Alpha Player", exact: true }).click();
	await expect(
		page.getByRole("dialog", { name: "Alpha Player" }),
	).toBeVisible();
	await expect(page).toHaveURL(
		(url) => url.searchParams.get("app") === ALPHA_PACKAGE,
	);
	await page.keyboard.press("Escape");
	await expect(page.getByRole("dialog")).toBeHidden();
	await expect(page).toHaveURL(background);
	await expect(search).toHaveValue("alpha");
	await page.goBack();
	await expect(
		page.getByRole("dialog", { name: "Alpha Player" }),
	).toBeVisible();
	await page.goForward();
	await expect(page.getByRole("dialog")).toBeHidden();
	await page.getByRole("link", { name: "Bundles", exact: true }).click();
	await expect(page).toHaveURL("/bundles");
});

test("opens deep links independently of the background tab", async ({
	page,
}) => {
	for (const [href, title, background] of [
		["/?github=Example/core", "Core patches", "/"],
		["/apps?gitlab=group/community", "Community patches", "/apps"],
		[
			`/whats-new?app=${ALPHA_PACKAGE}&patch=audio`,
			"Alpha Player",
			"/whats-new",
		],
	]) {
		await page.goto(href);
		const dialog = page.getByRole("dialog", { name: title, exact: true });
		await expect(dialog).toBeVisible();
		if (href.includes("patch="))
			await expect(
				dialog.getByText("Playback options", { exact: true }),
			).toBeVisible();
		await dialog.getByRole("button", { name: "Close modal" }).click();
		await expect(page).toHaveURL(background);
	}
});

test("previews Test Bundle branches and fetches fresh data when checked again", async ({
	page,
}) => {
	await page.goto("/bundles?sort=stars");
	await page.getByRole("button", { name: "Test bundle", exact: true }).click();
	await expect(page).toHaveURL("/bundles?sort=stars&test-bundle");
	const input = page.getByRole("dialog").getByRole("textbox");
	await input.fill("https://example.com/owner/repo");
	await page.getByRole("button", { name: "OK", exact: true }).click();
	await expect(page.getByRole("dialog")).toContainText(/HTTPS/);
	await input.fill("https://github.com/example/preview");
	await page.getByRole("button", { name: "OK", exact: true }).click();
	await expect(
		page.getByRole("dialog").getByText("Unlock premium", { exact: true }),
	).toBeVisible();
	await page.getByRole("button", { name: "dev", exact: true }).click();
	await expect(
		page.getByRole("dialog").getByText("New controls", { exact: true }),
	).toBeVisible();
	await page.getByRole("button", { name: "Close modal" }).click();
	await expect(page).toHaveURL("/bundles?sort=stars");
	await page.route(
		"https://raw.githubusercontent.com/example/preview/main/patches-list.json",
		(route) =>
			route.fulfill({
				json: {
					patches: [
						{
							name: "Refreshed preview",
							compatiblePackages: { [ALPHA_PACKAGE]: [] },
						},
					],
				},
			}),
	);
	await page.getByRole("button", { name: "Test bundle", exact: true }).click();
	await input.fill("https://github.com/example/preview");
	await page.getByRole("button", { name: "OK", exact: true }).click();
	await expect(
		page.getByRole("dialog").getByText("Refreshed preview", { exact: true }),
	).toBeVisible();
});

test("keeps the catalog and modal accessible without horizontal overflow", async ({
	page,
}) => {
	await page.goto("/");
	await expect(
		page.getByRole("button", { name: "Alpha Player", exact: true }),
	).toBeVisible();
	expect(
		(
			await new AxeBuilder({ page })
				.withTags(["wcag2a", "wcag2aa", "wcag21aa"])
				.analyze()
		).violations,
	).toEqual([]);
	await page.goto(`/?github=${CORE_KEY.split(":")[1]}`);
	const dialog = page.getByRole("dialog", { name: "Core patches" });
	await expect(dialog).toBeVisible();
	expect(
		(
			await new AxeBuilder({ page })
				.withTags(["wcag2a", "wcag2aa", "wcag21aa"])
				.analyze()
		).violations,
	).toEqual([]);
	expect(
		await page
			.locator("html")
			.evaluate((element) => element.scrollWidth <= element.clientWidth),
	).toBe(true);
	expect(
		await dialog.evaluate(
			(element) => element.scrollWidth <= element.clientWidth,
		),
	).toBe(true);
	await page.keyboard.press("Escape");
	await expect(dialog).toBeHidden();
});
