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

test('the stats page: behind the admin token, then the definition, honest denominators, the matrix and a disagreement', async ({ page, request }) => {
  await page.goto('/');
  await expect(page.getByText('Your messages are kept to compare AI models.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Stats' })).toHaveCount(0);
  await page.goto('/#/stats');
  await page.getByLabel('Admin token').fill('e2e-wrong-token');
  await page.getByRole('button', { name: 'Open the stats' }).click();
  await expect(page.getByRole('alert')).toHaveText('That token did not work, or the stats are switched off.');
  await page.getByLabel('Admin token').fill('e2e-fake-admin-token');
  await page.getByRole('button', { name: 'Open the stats' }).click();
  await expect(page.getByRole('region', { name: 'What agreement means' })).toContainText('not that either is right');
  await expect(page.getByTestId('compared-understand')).toContainText('165 of 228 decisions compared · 63 nimble errors');
  await expect(page.getByTestId('matrix-understand')).toBeVisible();
  await expect(page.getByLabel('jev chose search, nimble failed: 42')).toHaveText('42');
  await page.getByRole('button', { name: /differ on weight/ }).click();
  await expect(page.getByTestId('decision-dec-weight').locator('tr[data-disagree="true"]')).toHaveCount(1);
  await page.getByRole('button', { name: 'Back' }).click();
  await expect(page).toHaveURL(/#\/$/);
  await expect(page.getByRole('button', { name: 'New case' })).toBeVisible();
  expect(await (await request.get('http://127.0.0.1:8765/__auth_leaks')).json()).toEqual([]);
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

test('a save can be deleted from the title screen', async ({ page, request }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'New case' }).click();
  await expect(page).toHaveURL(/#\/game\/e2e-game$/);
  const origin = { origin: 'http://127.0.0.1:5174' };
  expect((await request.post('http://127.0.0.1:8765/api/games/e2e-game/save', { headers: origin })).ok()).toBe(true);
  await page.goto('/');
  const saves = page.getByRole('region', { name: 'Saved games' });
  await saves.getByRole('button', { name: 'Delete save 0123456789abcdef' }).click();
  await expect(saves.getByText('No saves yet.')).toBeVisible();
  expect(await (await request.get('http://127.0.0.1:8765/api/saves')).json()).toEqual([]);
});

test('each setting can be picked in turn, opens its room, and is named in the open games', async ({ page }) => {
  for (const [id, title, blurb] of [
    ['castle', 'The Castle', 'A murder at a country house.'],
    ['liner', 'The Liner', 'A death on an ocean liner.'],
  ] as const) {
    await page.goto('/');
    await page.getByRole('combobox', { name: 'Setting' }).selectOption(id);
    await expect(page.getByText(blurb)).toBeVisible();
    await page.getByRole('button', { name: 'New case' }).click();
    await expect(page.getByRole('navigation', { name: 'Notebook' })).toBeVisible();
    await page.goto('/');
    // the choice is remembered, and the server was told which pack to open
    await expect(page.getByRole('combobox', { name: 'Setting' })).toHaveValue(id);
    await expect(page.getByRole('region', { name: 'Open games' })).toContainText(title);
  }
});
