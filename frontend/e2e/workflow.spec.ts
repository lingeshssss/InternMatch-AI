import { test, expect } from '@playwright/test';
import { register, trackOrigins, deleteAccount } from './helpers';

// Uses the controlled postings seeded into the disposable e2e database by scripts/e2e.sh.
test('profile, strict evidence, explore statuses, search, saved jobs, tracking, mobile and theme', async ({ page, baseURL }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const foreign = trackOrigins(page, baseURL!);
  await register(page);
  await expect(page.getByRole('button', { name: /Strict Match/ })).toHaveClass(/active/);
  await expect(page.getByText('Your next match is worth verifying.')).toBeVisible();

  // Confirm a profile. Authorization is left blank first: case C keeps it UNKNOWN.
  await page.getByRole('button', { name: 'Profile', exact: true }).click();
  await page.getByLabel('University', { exact: true }).fill('Controlled Test University');
  await page.getByLabel('Expected graduation (month)').fill('2030-05');
  await page.getByLabel('Confirmed standing at internship start').selectOption('rising sophomore');
  await page.getByLabel('Internship term that standing applies to').selectOption('Summer 2027');
  await expect(page.getByLabel('Authorized to work in the United States')).toHaveValue('');
  await page.getByRole('button', { name: 'Confirm & save profile' }).click();
  await expect(page.getByRole('status')).toContainText('Confirmed qualifications saved');

  await page.getByRole('button', { name: 'Discover', exact: true }).click();
  await page.getByRole('button', { name: /Potential Match/ }).click();
  const verifiedCard = page.locator('article', { hasText: 'E2E Verified-Path Internship' });
  await expect(verifiedCard.getByText('Potentially Eligible')).toBeVisible();

  // Supplying authorization makes every mandatory rule pass -> Verified Eligible in Strict Match.
  await page.getByRole('button', { name: 'Profile', exact: true }).click();
  await page.getByLabel('Authorized to work in the United States').selectOption('true');
  await page.getByRole('button', { name: 'Confirm & save profile' }).click();
  await expect(page.getByRole('status')).toContainText('Confirmed qualifications saved');
  await page.reload();
  await page.getByRole('button', { name: 'Profile', exact: true }).click();
  await expect(page.getByLabel('Expected graduation (month)')).toHaveValue('2030-05');
  await page.getByRole('button', { name: 'Discover', exact: true }).click();
  await expect(page.getByRole('button', { name: /Strict Match/ })).toHaveClass(/active/);
  await expect(verifiedCard.getByText('Verified Eligible')).toBeVisible();
  await expect(page.locator('article', { hasText: 'E2E Academic Mismatch Internship' })).toHaveCount(0);

  // Evidence view: exact employer quote, per-requirement result and original source link.
  await verifiedCard.getByRole('button', { name: /View evidence/ }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByText('“Must graduate between December 2029 and June 2031.”')).toBeVisible();
  await expect(dialog.getByText('“Must be authorized to work in the United States.”')).toBeVisible();
  await expect(dialog.locator('.evidence-row .badge', { hasText: 'PASS' })).toHaveCount(2);
  await expect(dialog.getByRole('link', { name: /Employer source/ }).first()).toHaveAttribute('href', 'https://example.com/controlled/e2e-verified');
  await dialog.getByRole('button', { name: 'Save' }).click();
  await expect(page.getByRole('status')).toContainText('Opportunity saved');
  await dialog.getByRole('button', { name: 'Mark as applied' }).click();
  await expect(page.getByRole('status')).toContainText('Marked as applied');
  await page.keyboard.press('Escape');

  // Explore shows the academic failure (case B) and the inaccessible source (case F).
  await page.getByRole('button', { name: /Explore/ }).click();
  await expect(page.locator('article', { hasText: 'E2E Academic Mismatch Internship' }).getByText('Ineligible')).toBeVisible();
  await expect(page.locator('article', { hasText: 'E2E Inaccessible Source Internship' }).getByText('Unverified')).toBeVisible();
  await page.locator('article', { hasText: 'E2E Academic Mismatch Internship' }).getByRole('button', { name: /View evidence/ }).click();
  await expect(page.getByRole('dialog').locator('.evidence-row .badge', { hasText: 'FAIL' })).toBeVisible();
  await page.keyboard.press('Escape');

  // Search filters the catalogue.
  await page.getByLabel('Search internship titles').fill('Mismatch');
  await expect(page.locator('article')).toHaveCount(1);
  await page.getByLabel('Search internship titles').fill('');

  // Saved view lists every saved posting independent of the current page.
  await page.getByRole('button', { name: 'Saved', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Your shortlist.' })).toBeVisible();
  await expect(page.locator('article', { hasText: 'E2E Verified-Path Internship' })).toBeVisible();

  // Application tracking: move from Applied to Interview.
  await page.getByRole('button', { name: 'Applications', exact: true }).click();
  await page.locator('.kanban-column', { hasText: 'Applied' }).getByRole('button', { name: /E2E Verified-Path Internship/ }).click();
  await page.getByRole('dialog').getByLabel('Stage').selectOption('Interview');
  await page.getByRole('dialog').getByLabel('Notes').fill('Controlled test note');
  await page.getByRole('button', { name: 'Save application' }).click();
  await expect(page.getByRole('status')).toContainText('Application updated');
  await expect(page.locator('.kanban-column', { hasText: 'Interview' }).getByRole('button', { name: /E2E Verified-Path Internship/ })).toBeVisible();

  // Mobile layout has no horizontal overflow.
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Discover', exact: true }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
  await page.setViewportSize({ width: 1440, height: 1000 });

  await page.getByRole('button', { name: 'Settings & sources', exact: true }).click();
  await page.getByRole('button', { name: 'Toggle color theme' }).click();
  await expect(page.locator('body')).toHaveClass('dark');
  await deleteAccount(page);
  expect(foreign).toEqual([]);
  expect(errors).toEqual([]);
});
