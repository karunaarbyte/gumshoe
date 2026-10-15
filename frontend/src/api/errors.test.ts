import { expect, test } from 'vitest';
import { NETWORK, errorFrom } from './errors';

test('a gateway error from a proxy with no server behind it reads as unreachable', async () => {
  const e = await errorFrom(new Response('Bad Gateway', { status: 502 }));
  expect(e.code).toBe(NETWORK);
});

test('an API error body keeps its own code, even on a 503', async () => {
  const e = await errorFrom(new Response(JSON.stringify({ code: 'unavailable', message: 'game off' }), { status: 503 }));
  expect(e).toMatchObject({ code: 'unavailable', message: 'game off' });
});
