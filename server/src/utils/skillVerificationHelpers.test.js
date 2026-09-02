import { test } from 'node:test';
import assert from 'node:assert/strict';
import { isCacheFresh, buildNotConnectedResults } from './skillVerificationHelpers.js';

const DAY_MS = 24 * 60 * 60 * 1000;

test('isCacheFresh: null fetchedAt is never fresh', () => {
  assert.equal(isCacheFresh(null), false);
});

test('isCacheFresh: under 24h old is fresh', () => {
  const now = Date.now();
  const fetchedAt = new Date(now - DAY_MS + 1000).toISOString();
  assert.equal(isCacheFresh(fetchedAt, now), true);
});

test('isCacheFresh: over 24h old is stale', () => {
  const now = Date.now();
  const fetchedAt = new Date(now - DAY_MS - 1000).toISOString();
  assert.equal(isCacheFresh(fetchedAt, now), false);
});

test('buildNotConnectedResults: maps every skill row to a github_not_connected result', () => {
  const rows = [
    { skillId: 'skill-1', name: 'Python' },
    { skillId: 'skill-2', name: 'Kubernetes' },
  ];
  const results = buildNotConnectedResults(rows);
  assert.equal(results.length, 2);
  for (const r of results) {
    assert.equal(r.verified, false);
    assert.equal(r.method, 'unverified');
    assert.equal(r.confidence, null);
    assert.equal(r.evidenceRepoId, null);
    assert.equal(r.reason, 'github_not_connected');
  }
  assert.equal(results[0].skillId, 'skill-1');
  assert.equal(results[1].skillId, 'skill-2');
});

test('buildNotConnectedResults: empty input gives empty output', () => {
  assert.deepEqual(buildNotConnectedResults([]), []);
});
