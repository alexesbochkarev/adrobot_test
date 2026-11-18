import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  use: {
    baseURL: "http://127.0.0.1:5179",
    channel: process.env.PLAYWRIGHT_CHANNEL,
    viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run dev -- --port 5179",
    url: "http://127.0.0.1:5179",
    reuseExistingServer: false,
  },
});
