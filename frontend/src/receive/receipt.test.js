import assert from 'node:assert/strict';
import { test } from 'node:test';
import { checkReceipt, draftProblems, newReceipt, receiptPayload, receiptReducer, receiptTotalSatang } from './receipt.js';

const today = '2026-09-21';
const product = {
  id: 7,
  display_name: 'Amoxicillin 500 mg',
  units: [
    { id: 1, name: 'แผง', factor: 10, is_default: true },
    { id: 2, name: 'กล่อง', factor: 100, is_default: false },
  ],
};

function receiptWith(...actions) {
  return actions.reduce(receiptReducer, { ...newReceipt(today), supplierId: '3' });
}

test('scanning the same box again counts it until the lot is filled in', () => {
  let r = receiptWith({ type: 'add', product, unitId: 2 }, { type: 'add', product, unitId: 2 });
  assert.equal(r.lines.length, 1);
  assert.equal(r.lines[0].qty, '2');
  r = receiptReducer(r, { type: 'update', key: r.lines[0].key, changes: { lotNo: 'A1' } });
  r = receiptReducer(r, { type: 'add', product, unitId: 2 });
  assert.equal(r.lines.length, 2);
});

test('last cost fills an empty cost and follows a unit change', () => {
  let r = receiptWith({ type: 'add', product, unitId: 2 });
  r = receiptReducer(r, { type: 'lastCosts', productId: 7, costs: { 1: '24.00', 2: '230.00' } });
  assert.equal(r.lines[0].unitCost, '230.00');
  r = receiptReducer(r, { type: 'update', key: r.lines[0].key, changes: { unitId: 1 } });
  assert.equal(r.lines[0].unitCost, '24.00');
  r = receiptReducer(r, { type: 'update', key: r.lines[0].key, changes: { unitCost: '25' } });
  r = receiptReducer(r, { type: 'update', key: r.lines[0].key, changes: { unitId: 2 } });
  assert.equal(r.lines[0].unitCost, '25'); // typed by hand — left alone
});

test('posting needs lot, expiry, and cost; totals use whole satang', () => {
  let r = receiptWith({ type: 'add', product, unitId: 2 });
  const key = r.lines[0].key;
  assert.equal(checkReceipt(r, { today, nearExpiryDays: 180 }).ok, false);

  r = receiptReducer(r, { type: 'update', key, changes: { qty: '3', lotNo: 'A1', expiryText: '03/2028', unitCost: '230.10' } });
  const check = checkReceipt(r, { today, nearExpiryDays: 180 });
  assert.equal(check.ok, true, check.errors.join());
  assert.equal(receiptTotalSatang(r), 69030);

  const payload = receiptPayload(r, true);
  assert.deepEqual(payload.lines[0], { unit_id: 2, qty: 3, lot_no: 'A1', expiry_date: '2028-03-31', unit_cost: '230.10' });
  assert.equal(payload.supplier_id, 3);
});

test('expired stock is refused unless it is the opening balance', () => {
  let r = receiptWith({ type: 'add', product, unitId: 1 });
  const key = r.lines[0].key;
  r = receiptReducer(r, { type: 'update', key, changes: { lotNo: 'OLD', expiryText: '31/08/2569', unitCost: '0' } });
  assert.match(checkReceipt(r, { today, nearExpiryDays: 180 }).lines[key].errors.join(), /หมดอายุแล้ว/);
  r = receiptReducer(r, { type: 'set', fields: { isOpening: true } });
  const check = checkReceipt(r, { today, nearExpiryDays: 180 });
  assert.equal(check.ok, true);
  assert.match(check.lines[key].warnings.join(), /หมดอายุแล้ว/);
});

test('near expiry is a warning, not an error', () => {
  let r = receiptWith({ type: 'add', product, unitId: 1 });
  const key = r.lines[0].key;
  r = receiptReducer(r, { type: 'update', key, changes: { lotNo: 'N1', expiryText: '12/2026', unitCost: '20' } });
  const check = checkReceipt(r, { today, nearExpiryDays: 180 });
  assert.equal(check.ok, true);
  assert.match(check.lines[key].warnings.join(), /ใกล้หมดอายุ \(อีก 101 วัน\)/);
});

test('a known lot number with a different expiry is flagged', () => {
  const withLot = { ...product, lots: [{ lot_no: 'AX1', expiry_date: '2028-03-31', qty: 50 }] };
  let r = receiptWith({ type: 'add', product: withLot, unitId: 1 });
  const key = r.lines[0].key;
  r = receiptReducer(r, { type: 'update', key, changes: { lotNo: 'AX1', expiryText: '04/2028', unitCost: '20' } });
  assert.match(checkReceipt(r, { today, nearExpiryDays: 180 }).lines[key].warnings.join(), /ตรวจอีกครั้ง/);
  r = receiptReducer(r, { type: 'update', key, changes: { expiryText: '03/2028' } });
  assert.deepEqual(checkReceipt(r, { today, nearExpiryDays: 180 }).lines[key].warnings, []);
});

test('a draft can be incomplete but not unreadable', () => {
  let r = receiptWith({ type: 'add', product, unitId: 1 });
  assert.deepEqual(draftProblems(r), []);
  assert.equal(receiptPayload(r, false).lines[0].unit_cost, null); // not entered ≠ free goods
  r = receiptReducer(r, { type: 'update', key: r.lines[0].key, changes: { expiryText: 'ปีหน้า' } });
  assert.equal(draftProblems(r).length, 1);
});
