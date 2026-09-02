import { test } from 'node:test';
import assert from 'node:assert/strict';
import { isCacheFresh } from './codeAnalysisHelpers.js';

const DAY_MS = 24 * 60 * 60 * 1000;

test('isCacheFresh: null analyzedAt is never fresh', () => {
  assert.equal(isCacheFresh(null), false);
});

test('isCacheFresh: under 24h old is fresh', () => {
  const now = Date.now();
  const analyzedAt = new Date(now - DAY_MS + 1000).toISOString();
  assert.equal(isCacheFresh(analyzedAt, now), true);
});

test('isCacheFresh: over 24h old is stale', () => {
  const now = Date.now();
  const analyzedAt = new Date(now - DAY_MS - 1000).toISOString();
  assert.equal(isCacheFresh(analyzedAt, now), false);
});
