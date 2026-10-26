import { test, expect } from '@playwright/test';
import { register, password, trackOrigins, deleteAccount } from './helpers';

test('same-origin registration, session persistence, logout and login', async ({ page, context, baseURL }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const foreign = trackOrigins(page, baseURL!);
  const apiCalls: string[] = [];
  page.on('response', (r) => r.url().includes('/api/') && apiCalls.push(`${r.request().method()} ${new URL(r.url()).pathname} ${r.status()}`));

  const email = await register(page);
  const session = (await context.cookies()).find((c) => c.name === 'internmatch_session');
  expect(session, 'session cookie set on the app origin').toBeTruthy();
  expect(session!.httpOnly).toBe(true);
  expect(session!.sameSite).toBe('Lax');
  expect(session!.domain).toBe(new URL(baseURL!).hostname);

  // Refresh: the session survives a full reload.
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Find your next beginning.' })).toBeVisible();

  // Authenticated request from the page succeeds through the proxy.
  const me = await page.evaluate(async () => (await fetch('/api/auth/me')).json());
  expect(me.email).toBe(email);

  // Logout revokes the session server-side.
  await page.getByRole('button', { name: 'Settings & sources', exact: true }).click();
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('heading', { name: 'Welcome back.' })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Welcome back.' })).toBeVisible();
  expect(await page.evaluate(async () => (await fetch('/api/auth/me')).status)).toBe(401);

  // Wrong password is rejected with a clear message.
  await page.getByLabel('Email address').fill(email);
  await page.getByLabel(/^Password/).fill('definitely the wrong password');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.locator('.error[role=alert]')).toContainText('Invalid credentials');

  // Correct login.
  await page.getByLabel(/^Password/).fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Find your next beginning.' })).toBeVisible();

  // A cross-origin write is refused even with the session cookie (CSRF Origin check).
  const forged = await page.request.post('/api/auth/logout', { headers: { Origin: 'https://evil.example' } });
  expect(forged.status()).toBe(403);

  await deleteAccount(page);
  expect(foreign, 'requests to other origins').toEqual([]);
  expect(apiCalls.some((c) => c.startsWith('POST /api/auth/register 200'))).toBe(true);
  expect(errors).toEqual([]);
});
