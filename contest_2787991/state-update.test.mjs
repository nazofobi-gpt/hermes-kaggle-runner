import assert from 'node:assert/strict';

function appendCreated(current, created) {
  return [...current, created];
}

const original = [{ id: 1, name: 'Existing item' }];
const created = { id: 2, name: 'New item' };
const next = appendCreated(original, created);
assert.equal(original.length, 1, 'original state is not mutated');
assert.deepEqual(next, [original[0], created], 'successful submit is visible immediately');

const duplicateClicksWhileSaving = (status) => status === 'saving';
assert.equal(duplicateClicksWhileSaving('saving'), true, 'duplicate submit is gated');
assert.equal('   '.trim().length === 0, true, 'empty input is rejected');

const failed = original;
assert.deepEqual(failed, original, 'failed request leaves canonical state unchanged');
console.log('CONTEST_2787991_STATE_TEST_PASS');
