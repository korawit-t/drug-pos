import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  checkSheet,
  countedQty,
  difference,
  draftProblems,
  newSheet,
  sheetPayload,
  sheetReducer,
  sheetSummary,
} from './sheet.js';

const today = '2026-09-23';
const lot = (over = {}) => ({
  id: 5,
  product_id: 1,
  product_name: 'Amoxicillin 500 mg',
  base_unit: 'แคปซูล',
  storage_location: '',
  lot_no: 'A1',
  expiry_date: '2028-03-31',
  qty: 200,
  expired: false,
  units: [{ name: 'แผง', factor: 10 }],
  ...over,
});

const sheetWith = (...actions) => actions.reduce(sheetReducer, newSheet(today));
const only = (sheet) => sheet.lines[0];
const check = (sheet) => checkSheet(sheet, { today });

test('the same lot is only added once', () => {
  const sheet = sheetWith({ type: 'add', lots: [lot()] }, { type: 'add', lots: [lot(), lot({ id: 6, lot_no: 'B2' })] });
  assert.deepEqual(
    sheet.lines.map((l) => l.lot.lot_no),
    ['A1', 'B2'],
  );
  assert.equal(only(sheet).systemQty, 200);
});

test('counting in packs adds the loose ones on top', () => {
  let sheet = sheetWith({ type: 'add', lots: [lot()] });
  const key = only(sheet).key;
  sheet = sheetReducer(sheet, { type: 'update', key, changes: { factor: 10, qtyText: '19', looseText: '7' } });
  assert.equal(countedQty(only(sheet)), 197);
  assert.equal(difference(only(sheet)), -3);
});

test('typing a difference fills in the count, and counting again clears the typed difference', () => {
  let sheet = sheetWith({ type: 'add', lots: [lot()] });
  const key = only(sheet).key;
  sheet = sheetReducer(sheet, { type: 'difference', key, text: '-5' }); // ของแตก 5 แคปซูล
  assert.equal(only(sheet).qtyText, '195');
  assert.equal(countedQty(only(sheet)), 195);

  sheet = sheetReducer(sheet, { type: 'update', key, changes: { qtyText: '198' } });
  assert.equal(only(sheet).diffText, null);
  assert.equal(difference(only(sheet)), -2);
});

test('a difference bigger than the shelf is refused instead of going negative', () => {
  let sheet = sheetWith({ type: 'add', lots: [lot({ qty: 3 })] });
  const key = only(sheet).key;
  sheet = sheetReducer(sheet, { type: 'difference', key, text: '-5' });
  assert.equal(countedQty(only(sheet)), null);
  assert.match(check(sheet).lines[key].errors.join(), /ตัดออกได้มากที่สุด 3/);
});

test('a difference needs a reason, and "other" needs a note', () => {
  let sheet = sheetWith({ type: 'add', lots: [lot()] });
  const key = only(sheet).key;
  sheet = sheetReducer(sheet, { type: 'update', key, changes: { qtyText: '195' } });
  assert.match(check(sheet).lines[key].errors.join(), /เลือกสาเหตุ/);

  sheet = sheetReducer(sheet, { type: 'update', key, changes: { reason: 'other' } });
  assert.match(check(sheet).lines[key].errors.join(), /หมายเหตุ/);

  sheet = sheetReducer(sheet, { type: 'update', key, changes: { note: 'ยกให้โรงพยาบาล' } });
  assert.equal(check(sheet).ok, true);
  assert.deepEqual(sheetPayload(sheet, true, { pharmacistId: 3, pin: '4821' }).lines[0], {
    lot_id: 5,
    system_qty: 200,
    counted_qty: 195,
    reason: 'other',
    note: 'ยกให้โรงพยาบาล',
  });
});

test('a count that matches needs no reason', () => {
  let sheet = sheetWith({ type: 'add', lots: [lot()] });
  sheet = sheetReducer(sheet, { type: 'update', key: only(sheet).key, changes: { qtyText: '200' } });
  assert.equal(check(sheet).ok, true);
  assert.deepEqual(sheetSummary(sheet), { lines: 1, counted: 1, uncounted: 0, shortage: 0, surplus: 0, differing: 0 });
});

test('an uncounted line blocks the adjustment but not a draft', () => {
  const sheet = sheetWith({ type: 'add', lots: [lot()] });
  assert.match(check(sheet).errors.join(), /1 รายการที่ยังนับไม่ครบ/);
  assert.deepEqual(draftProblems(sheet), []);
  assert.equal(sheetPayload(sheet, false).lines[0].counted_qty, null);
});

test('refreshing keeps the count but flags what moved', () => {
  let sheet = sheetWith({ type: 'add', lots: [lot(), lot({ id: 6, lot_no: 'B2', qty: 50 })] });
  sheet = sheetReducer(sheet, { type: 'update', key: only(sheet).key, changes: { qtyText: '195', reason: 'damaged' } });
  sheet = sheetReducer(sheet, { type: 'refresh', lots: [lot({ qty: 190 }), lot({ id: 6, lot_no: 'B2', qty: 50 })] });

  const [first, second] = sheet.lines;
  assert.equal(first.qtyText, '195'); // นับได้เท่าเดิม
  assert.equal(first.systemQty, 190);
  assert.equal(difference(first), 5);
  assert.equal(first.stale, true);
  assert.equal(second.stale, false);
  assert.match(check(sheet).lines[first.key].warnings.join(), /ยอดในระบบเปลี่ยนเป็น 190/);
});

test('expired lots can be added already written off', () => {
  const sheet = sheetWith({
    type: 'add',
    lots: [lot({ expired: true, qty: 10 })],
    prefill: { qtyText: '0', reason: 'expired' },
  });
  assert.equal(countedQty(only(sheet)), 0);
  assert.equal(check(sheet).ok, true);
  assert.equal(sheetSummary(sheet).shortage, 10);
});

test('expired stock left on the shelf is a warning, not an error', () => {
  let sheet = sheetWith({ type: 'add', lots: [lot({ expired: true, qty: 10 })] });
  const key = only(sheet).key;
  sheet = sheetReducer(sheet, { type: 'update', key, changes: { qtyText: '10' } });
  assert.equal(check(sheet).ok, true);
  assert.match(check(sheet).lines[key].warnings.join(), /หมดอายุแล้ว/);

  sheet = sheetReducer(sheet, { type: 'update', key, changes: { qtyText: '0', reason: 'expired' } });
  assert.deepEqual(check(sheet).lines[key].warnings, []);
  assert.deepEqual(sheetSummary(sheet), { lines: 1, counted: 1, uncounted: 0, shortage: 10, surplus: 0, differing: 1 });
});

test('a reopened draft flags lots that moved, a posted sheet does not', () => {
  const item = {
    id: 1,
    lot: lot({ qty: 195 }),
    system_qty: 200,
    counted_qty: 195,
    difference: -5,
    reason: 'damaged',
    reason_label: 'ชำรุด / แตก / หก',
    note: '',
  };
  const saved = (status) => ({
    id: 3,
    status,
    counted_date: today,
    note: '',
    created_by: 'พนักงาน',
    posted_by: '',
    approved_by: '',
    posted_at: null,
    items: [item],
  });

  const draft = sheetReducer(newSheet(today), { type: 'load', count: saved('draft') });
  assert.equal(only(draft).stale, true);
  assert.equal(only(draft).qtyText, '195');

  const posted = sheetReducer(newSheet(today), { type: 'load', count: saved('posted') });
  assert.equal(only(posted).stale, false);
  assert.deepEqual(checkSheet(posted, { today }).lines[only(posted).key].warnings, []);
});

test('a number we cannot read is kept out of both a draft and an adjustment', () => {
  let sheet = sheetWith({ type: 'add', lots: [lot()] });
  const key = only(sheet).key;
  sheet = sheetReducer(sheet, { type: 'update', key, changes: { qtyText: 'สองร้อย' } });
  assert.ok(Number.isNaN(countedQty(only(sheet))));
  assert.equal(draftProblems(sheet).length, 1);
  assert.equal(check(sheet).ok, false);
});
