import { defineConfig } from '@playwright/test';

// Run through scripts/e2e.sh, which starts disposable same-origin stacks:
//   E2E_URL         full stack with the local AI runtime   (default http://localhost:8090)
//   E2E_AI_DOWN_URL stack whose AI runtime is unreachable  (default http://localhost:8091)
const live = process.env.E2E_URL || 'http://localhost:8090';
const down = process.env.E2E_AI_DOWN_URL || 'http://localhost:8091';
export default defineConfig({
  testDir: './e2e',
  workers: 1,
  timeout: 240_000,
  reporter: 'list',
  use: { headless: true, trace: 'retain-on-failure' },
  projects: [
    { name: 'same-origin', testMatch: /(auth|workflow)\.spec\.ts/, use: { baseURL: live } },
    { name: 'local-ai', testMatch: /resume-ai\.spec\.ts/, use: { baseURL: live } },
    { name: 'ai-down', testMatch: /ai-down\.spec\.ts/, use: { baseURL: down } },
  ],
});
