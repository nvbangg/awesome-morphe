import { defineConfig, devices } from "@playwright/test";

const BASE_URL = "http://localhost:4173";

export default defineConfig({
	testDir: "./e2e",
	use: { baseURL: BASE_URL, trace: "retain-on-failure" },
	projects: [
		{ name: "desktop", use: { ...devices["Desktop Chrome"] } },
		{ name: "mobile", use: { ...devices["Pixel 5"] } },
	],
	webServer: { command: "pnpm preview", url: BASE_URL },
});
