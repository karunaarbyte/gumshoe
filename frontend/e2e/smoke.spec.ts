import { expect, test } from '@playwright/test';

// the fake API holds one global game, so the tests must not run in parallel
test.describe.configure({ mode: 'serial' });

test('new case, a turn, an accusation, confirm, game over and the reveal', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  await page.getByRole('button', { name: 'New case' }).click();
  await expect(page.getByRole('navigation', { name: 'Notebook' })).toBeVisible();
  await expect(page).toHaveURL(/#\/game\/e2e-game$/);

  const box = page.getByRole('textbox', { name: 'Message' });
  await box.fill('search the long gallery');
  await box.press('Enter');
  await expect(page.getByText('You find a stained glass by the body.')).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Notebook' })).toContainText('A stained glass lies by the body.');

  await page.getByRole('button', { name: 'Accuse' }).click();
  await expect(box).toHaveValue('I accuse ');
  await box.fill('I accuse Mr Grey, poisoned port, unpaid inheritance');
  await box.press('Enter');
  const card = page.getByRole('region', { name: 'Accusation confirmation' });
  await expect(card).toContainText('Accuse Mr Grey the butler');

  await page.reload(); // the waiting confirmation survives a reload
  await expect(page.getByRole('region', { name: 'Accusation confirmation' }).getByRole('button', { name: 'Yes' })).toBeEnabled();
  await page.getByRole('region', { name: 'Accusation confirmation' }).getByRole('button', { name: 'Yes' }).click();

  const result = page.getByRole('dialog', { name: 'Case result' });
  await expect(result).toContainText('CASE CLOSED');
  await expect(result.getByRole('article', { name: 'The answer' })).toContainText('poisoned port');

  await result.getByRole('button', { name: 'Back to the board' }).click();
  await page.getByRole('button', { name: 'Open the trace' }).click();
  await page.getByRole('button', { name: /search the long gallery/ }).click();
  await expect(page.getByTestId('decision-d-search').locator('tr[data-disagree="true"]')).toHaveCount(1);
});

test('the stats page: the definition, honest denominators, the matrix and a disagreement', async ({ page }) => {
  await page.goto('/#/stats');
  await expect(page.getByRole('region', { name: 'What agreement means' })).toContainText('not that either is right');
  await expect(page.getByTestId('compared-understand')).toContainText('165 of 228 decisions compared · 63 nimble errors');
  await expect(page.getByTestId('matrix-understand')).toBeVisible();
  await expect(page.getByLabel('jev chose search, nimble failed: 42')).toHaveText('42');
  await page.getByRole('button', { name: /differ on weight/ }).click();
  await expect(page.getByTestId('decision-dec-weight').locator('tr[data-disagree="true"]')).toHaveCount(1);
  await page.getByRole('button', { name: 'Back' }).click();
  await expect(page).toHaveURL(/#\/$/);
});

test('a typed yes carries the waiting pending_id and a bare yes carries none', async ({ page, request }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  await page.getByRole('button', { name: 'New case' }).click();
  await expect(page).toHaveURL(/#\/game\/e2e-game$/);
  const box = page.getByRole('textbox', { name: 'Message' });

  await box.fill('yes');
  await box.press('Enter');
  await expect(page.getByText('Ask about a suspect, search a place, or accuse.')).toBeVisible();

  await box.fill('I accuse Mr Grey, poisoned port, unpaid inheritance');
  await box.press('Enter');
  await expect(page.getByRole('region', { name: 'Accusation confirmation' })).toContainText('Accuse Mr Grey the butler');
  await box.fill('yes');
  await box.press('Enter');
  await expect(page.getByRole('dialog', { name: 'Case result' })).toContainText('CASE CLOSED');

  const sent = (await (await request.get('http://127.0.0.1:8765/__requests')).json()) as {
    route: string;
    body: { text?: string; pending_id?: string };
  }[];
  const yesTurns = sent.filter((r) => r.route === 'turn' && r.body.text === 'yes');
  expect(yesTurns).toHaveLength(2);
  expect(yesTurns[0]?.body).not.toHaveProperty('pending_id');
  expect(yesTurns[1]?.body.pending_id).toBe('p-e2e');
});
