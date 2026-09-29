import { defineConfig, devices } from "@playwright/test";

// End-to-end UI tests (npm run test:e2e). Kept out of tools/run_tests.sh
// because they need a downloaded browser: `npx playwright install chromium`.
export default defineConfig({
  testDir: "e2e",
  fullyParallel: true,
  reporter: [["list"]],
  use: { baseURL: "http://127.0.0.1:8798", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1400, height: 900 } } }],
  webServer: {
    command: "node e2e/serve-fixtures.ts",
    url: "http://127.0.0.1:8796/api/data",
    reuseExistingServer: false,
    stdout: "ignore",
  },
});
