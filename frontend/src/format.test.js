import assert from 'node:assert/strict';
import { test } from 'node:test';
import { parseExpiry, thaiDate, toGregorianDate } from './format.js';

test('month-only expiry means the last day of that month', () => {
  assert.equal(parseExpiry('03/2028').iso, '2028-03-31');
  assert.equal(parseExpiry('2/2028').iso, '2028-02-29');
  assert.equal(parseExpiry('02-2027').iso, '2027-02-28');
});

test('Buddhist years are converted, in 4 or 2 digits', () => {
  assert.equal(parseExpiry('31/03/2571').iso, '2028-03-31');
  assert.equal(parseExpiry('03/71').iso, '2028-03-31');
  assert.equal(parseExpiry('03/28').iso, '2028-03-31');
  assert.equal(parseExpiry('15.06.2570').iso, '2027-06-15');
});

test('ISO dates pass through', () => {
  assert.equal(parseExpiry('2028-03-31').iso, '2028-03-31');
});

test('what the screen shows can be read back', () => {
  assert.equal(parseExpiry(thaiDate('2028-03-31')).iso, '2028-03-31');
});

test('bad input explains itself instead of guessing', () => {
  assert.deepEqual(parseExpiry(''), { iso: null, error: null });
  assert.equal(parseExpiry('13/2028').error, 'เดือนไม่ถูกต้อง');
  assert.equal(parseExpiry('31/02/2028').error, 'วันที่ไม่ถูกต้อง');
  assert.ok(parseExpiry('March 2028').error);
  assert.ok(parseExpiry('3/2028/1/1').error);
});

test('date inputs typed in พ.ศ. become ค.ศ.', () => {
  assert.equal(toGregorianDate('2569-09-21'), '2026-09-21');
  assert.equal(toGregorianDate('2026-09-21'), '2026-09-21');
});
