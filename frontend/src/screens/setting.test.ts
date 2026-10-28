import { afterEach, describe, expect, test, vi } from 'vitest';
import { meta } from '../test/fixtures';
import { pickSetting, readSetting, writeSetting } from './setting';

afterEach(() => vi.restoreAllMocks());

describe('pickSetting', () => {
  test('returns the remembered pack when it exists', () => {
    expect(pickSetting(meta.packs, 'liner').id).toBe('liner');
  });
  test('an unknown remembered id falls back to castle', () => {
    expect(pickSetting(meta.packs, 'gone').id).toBe('castle');
    expect(pickSetting(meta.packs, null).id).toBe('castle');
  });
  test('with no castle it returns the first', () => {
    const [, liner] = meta.packs;
    expect(pickSetting([liner!], 'gone').id).toBe('liner');
  });
});

describe('remembered setting storage', () => {
  test('round-trips', () => {
    expect(readSetting()).toBeNull();
    writeSetting('liner');
    expect(readSetting()).toBe('liner');
  });
  test('readSetting is null and writeSetting is silent when localStorage throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(readSetting()).toBeNull();
    expect(() => writeSetting('liner')).not.toThrow();
  });
});
