import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeNumberInput } from './numberInput.js';
import { z } from 'zod';

const schema = z.number().int().min(1).max(120);
const cases = [
  ['', false], ['abc', false], ['0', false], ['1', true], ['42', true], ['120', true], ['121', false], ['1.5', false], ['-3', false],
];
for (const [raw, expected] of cases) {
  test(`raw=${JSON.stringify(raw)} expected=${expected}`, () => {
    const normalized = normalizeNumberInput(raw);
    assert.equal(schema.safeParse(normalized).success, expected);
  });
}

test('valid DOM string becomes a number', () => assert.equal(normalizeNumberInput('42'), 42));
test('empty becomes undefined rather than zero', () => assert.equal(normalizeNumberInput(''), undefined));
test('non-numeric becomes NaN and fails strict z.number', () => assert.equal(schema.safeParse(normalizeNumberInput('abc')).success, false));
