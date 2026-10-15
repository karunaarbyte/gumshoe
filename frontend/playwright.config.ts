import { defineConfig, devices } from '@playwright/test';

// The smoke test runs against e2e/fake-api.mjs only, never the real (billed) backend:
// both servers are started here and never reused, and the dev server's proxy points at the fake.
const FAKE_API_PORT = 8765;
const UI_PORT = 5174;

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  retries: 0,
  use: { baseURL: `http://127.0.0.1:${UI_PORT}`, viewport: { width: 1280, height: 860 } },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 860 } } }],
  webServer: [
    {
      command: `node e2e/fake-api.mjs ${FAKE_API_PORT}`,
      url: `http://127.0.0.1:${FAKE_API_PORT}/api/health`,
      reuseExistingServer: false,
    },
    {
      command: `npx vite --host 127.0.0.1 --port ${UI_PORT} --strictPort`,
      url: `http://127.0.0.1:${UI_PORT}`,
      env: { GUMSHOE_API_URL: `http://127.0.0.1:${FAKE_API_PORT}` },
      reuseExistingServer: false,
    },
  ],
});
