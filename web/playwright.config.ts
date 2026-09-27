import { defineConfig, devices } from "@playwright/test";

// Mocked journeys run against `vite preview` of the production build; the
// API is mocked per test (e2e/mock.ts). `BACKEND_URL` enables the live
// project against a real server (e2e/live.spec.ts).
export default defineConfig({
  testDir: "e2e",
  timeout: 45_000,
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: { baseURL: "http://127.0.0.1:4173", trace: "retain-on-failure" },
  projects: [
    {
      name: "desktop",
      testIgnore: /live\.spec/,
      use: { ...devices["Desktop Chrome"], colorScheme: "light" },
    },
    {
      name: "mobile",
      testIgnore: /live\.spec/,
      testMatch: /journeys\.spec/,
      grep: /Explore|Edition|Ask/,
      use: { ...devices["Pixel 7"], colorScheme: "dark" },
    },
    ...(process.env.BACKEND_URL
      ? [
          {
            name: "live",
            testMatch: /live\.spec/,
            use: { ...devices["Desktop Chrome"], baseURL: process.env.BACKEND_URL },
          },
        ]
      : []),
  ],
  webServer: {
    command: "npx vite preview --host 127.0.0.1 --port 4173 --strictPort",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
  },
});
