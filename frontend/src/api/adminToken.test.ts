import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { clearAdminToken, getAdminToken, setAdminToken } from './adminToken';

beforeEach(() => {
  clearAdminToken();
  sessionStorage.clear();
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  clearAdminToken();
});

test('a token round-trips and is cleared', () => {
  expect(getAdminToken()).toBeNull();
  setAdminToken('abc');
  expect(getAdminToken()).toBe('abc');
  clearAdminToken();
  expect(getAdminToken()).toBeNull();
});

test('it lives in sessionStorage, never localStorage or a cookie', () => {
  setAdminToken('abc');
  expect(sessionStorage.getItem('gumshoe.admin')).toBe('abc');
  expect(localStorage.getItem('gumshoe.admin')).toBeNull();
  expect(localStorage.length).toBe(0);
  expect(document.cookie).not.toContain('abc');
});

test('clearing removes it from sessionStorage too', () => {
  setAdminToken('abc');
  clearAdminToken();
  expect(sessionStorage.getItem('gumshoe.admin')).toBeNull();
});

test('when storage throws it still works from memory', () => {
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('blocked');
  });
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new Error('blocked');
  });
  vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
    throw new Error('blocked');
  });
  setAdminToken('mem');
  expect(getAdminToken()).toBe('mem');
  clearAdminToken();
  expect(getAdminToken()).toBeNull();
});

test('the token is never logged', () => {
  const spies = (['log', 'info', 'warn', 'error', 'debug'] as const).map((m) => vi.spyOn(console, m).mockImplementation(() => undefined));
  setAdminToken('secret-tok');
  getAdminToken();
  clearAdminToken();
  for (const s of spies) expect(JSON.stringify(s.mock.calls)).not.toContain('secret-tok');
});
