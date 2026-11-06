import { defineConfig } from "vitest/config";

export default defineConfig({
	resolve: { tsconfigPaths: true },
	test: { include: ["tests/**/*.test.ts"] },
});
