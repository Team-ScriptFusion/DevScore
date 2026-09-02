import { test } from 'node:test';
import assert from 'node:assert/strict';
import { isOwnedCandidate } from './candidateOwnership.js';

test('isOwnedCandidate: false when user does not exist', () => {
  assert.equal(isOwnedCandidate(null, [{ id: 'app-1' }]), false);
});

test('isOwnedCandidate: false when user is not a student', () => {
  const recruiter = { id: 'u1', role: 'recruiter' };
  assert.equal(isOwnedCandidate(recruiter, [{ id: 'app-1' }]), false);
});

test('isOwnedCandidate: false when there are no applications', () => {
  const student = { id: 'u1', role: 'student' };
  assert.equal(isOwnedCandidate(student, []), false);
});

test('isOwnedCandidate: true for a student with at least one application', () => {
  const student = { id: 'u1', role: 'student' };
  assert.equal(isOwnedCandidate(student, [{ id: 'app-1' }]), true);
});
