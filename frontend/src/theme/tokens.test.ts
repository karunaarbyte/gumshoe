import { expect, test } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { colors } from './tokens';

// read from disk: Vitest does not process CSS imports
const css = readFileSync(resolve(process.cwd(), 'src/theme/index.css'), 'utf8');

test('the CSS theme carries the same Newsprint values as tokens.ts', () => {
  expect(css).toContain(`--color-paper: ${colors.paper};`);
  expect(css).toContain(`--color-card: ${colors.card};`);
  expect(css).toContain(`--color-card-light: ${colors.cardLight};`);
  expect(css).toContain(`--color-ink: ${colors.ink};`);
  expect(css).toContain(`--color-stamp: ${colors.stamp};`);
});

test('fonts are self-hosted from fontsource, never a CDN', () => {
  expect(css).toContain("@import '@fontsource/courier-prime/400.css';");
  expect(css).toContain("@import '@fontsource/special-elite/400.css';");
  expect(css).not.toMatch(/https?:\/\//);
});

test('the desk keeps a 1100px minimum width and honours reduced motion', () => {
  expect(css).toContain('min-width: 1100px;');
  expect(css).toContain('@media (prefers-reduced-motion: reduce)');
});
