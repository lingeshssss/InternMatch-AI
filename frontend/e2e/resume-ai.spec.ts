import path from 'node:path';
import { test, expect } from '@playwright/test';
import { register, deleteAccount } from './helpers';

test('resume extraction with the local model requires review before confirmation', async ({ page }) => {
  await register(page);
  await page.getByRole('button', { name: 'Settings & sources', exact: true }).click();
  await expect(page.getByTestId('ai-status')).toHaveText('ollama ready');
  await page.getByRole('button', { name: 'Profile', exact: true }).click();
  // A previously confirmed value must survive reviewing a resume draft (regression: drafts used to overwrite it with null).
  await page.getByLabel('Confirmed standing at internship start').selectOption('rising sophomore');
  await page.getByRole('button', { name: 'Confirm & save profile' }).click();
  await expect(page.getByRole('status')).toContainText('Confirmed qualifications saved');
  await page.locator('input[type=file]').setInputFiles(path.join(__dirname, 'fixtures/resume.docx'));
  await expect(page.getByTestId('resume-review')).toBeVisible({ timeout: 200_000 });
  // Draft values come from the document; nothing is used until the student confirms.
  await expect(page.getByLabel('University', { exact: true })).toHaveValue(/State Test University/);
  await expect(page.getByLabel('Authorized to work in the United States')).toHaveValue('');
  await expect(page.getByLabel('Confirmed standing at internship start')).toHaveValue('rising sophomore');
  expect((await page.evaluate(async () => (await fetch('/api/profile')).json())).university).toBeNull();
  await page.getByRole('button', { name: 'Confirm reviewed resume qualifications' }).click();
  await expect(page.getByRole('status')).toContainText('Confirmed qualifications saved');
  expect((await page.evaluate(async () => (await fetch('/api/profile')).json())).university).toMatch(/State Test University/);
  await deleteAccount(page);
});
