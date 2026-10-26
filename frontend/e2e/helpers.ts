import { expect, type Page } from '@playwright/test';

export const password = 'controlled browser test password';

/** Fail the test if the page talks to any origin other than its own (e.g. a stale localhost:8000 build). */
export function trackOrigins(page: Page, baseURL: string) {
  const foreign: string[] = [];
  const origin = new URL(baseURL).origin;
  page.on('request', (r) => {
    const u = new URL(r.url());
    if (u.protocol.startsWith('http') && u.origin !== origin) foreign.push(r.url());
  });
  return foreign;
}

export async function register(page: Page, email = `browser-${Date.now()}-${Math.random().toString(36).slice(2, 7)}@example.com`) {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Welcome back.' })).toBeVisible();
  await page.getByRole('button', { name: 'New here? Create an account' }).click();
  await page.getByLabel('Email address').fill(email);
  await page.getByLabel(/^Password/).fill(password);
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Find your next beginning.' })).toBeVisible();
  return email;
}

export async function deleteAccount(page: Page) {
  await page.getByRole('button', { name: 'Settings & sources', exact: true }).click();
  page.once('dialog', (d) => d.accept());
  await page.getByRole('button', { name: 'Delete account', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Welcome back.' })).toBeVisible();
}
