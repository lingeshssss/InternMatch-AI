import path from 'node:path';
import { test, expect } from '@playwright/test';
import { register, deleteAccount } from './helpers';

test('local AI unavailable: clear status, no fabricated extraction, manual entry still works', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await register(page);
  await page.getByRole('button', { name: 'Settings & sources', exact: true }).click();
  await expect(page.getByTestId('ai-status')).toHaveText('ollama: not ready');
  await expect(page.getByText(/not reachable/)).toBeVisible();
  await page.getByRole('button', { name: 'Profile', exact: true }).click();
  await page.locator('input[type=file]').setInputFiles(path.join(__dirname, 'fixtures/resume.docx'));
  await expect(page.locator('.error[role=alert]')).toContainText('AI extraction unavailable');
  await expect(page.locator('.error[role=alert]')).toContainText('enter your qualifications manually');
  await expect(page.getByText('Extraction unavailable — enter details manually')).toBeVisible();
  await expect(page.getByLabel('University', { exact: true })).toHaveValue('');
  await page.getByLabel('University', { exact: true }).fill('Manually Entered University');
  await page.getByRole('button', { name: 'Confirm reviewed resume qualifications' }).click();
  await expect(page.getByRole('status')).toContainText('Confirmed qualifications saved');
  await deleteAccount(page);
  expect(errors).toEqual([]);
});
