import assert from 'node:assert/strict';
import { test } from 'node:test';
import { assign, fieldAt, mappedCount, missingRequired, signatureOf } from './mapping.js';

const FIELDS = [
  { name: 'trade_name', label: 'ชื่อการค้า', required: true },
  { name: 'unit_name', label: 'หน่วยขาย', required: true },
  { name: 'price1', label: 'ราคา 1', required: true },
  { name: 'code', label: 'รหัสสินค้า', required: false },
];

test('a field moves to the column it was picked in', () => {
  let mapping = {};
  mapping = assign(mapping, 1, 'trade_name');
  assert.deepEqual(mapping, { trade_name: 1 });
  assert.equal(fieldAt(mapping, 1), 'trade_name');
  assert.equal(fieldAt(mapping, 0), '');

  // ย้ายไปคอลัมน์อื่น — ของเดิมต้องหลุด ไม่ใช่มีสองที่
  mapping = assign(mapping, 3, 'trade_name');
  assert.deepEqual(mapping, { trade_name: 3 });
});

test('picking a different field for a column replaces what was there', () => {
  let mapping = assign({}, 2, 'code');
  mapping = assign(mapping, 2, 'unit_name');
  assert.deepEqual(mapping, { unit_name: 2 });
});

test('a column can be set back to unused', () => {
  let mapping = assign({}, 2, 'code');
  mapping = assign(mapping, 2, '');
  assert.deepEqual(mapping, {});
  assert.equal(mappedCount(mapping), 0);
});

test('required fields that are still unmatched are reported', () => {
  let mapping = assign({}, 0, 'trade_name');
  assert.deepEqual(
    missingRequired(mapping, FIELDS).map((f) => f.name),
    ['unit_name', 'price1'],
  );
  mapping = assign(assign(mapping, 1, 'unit_name'), 2, 'price1');
  assert.deepEqual(missingRequired(mapping, FIELDS), []);
});

test('the same export shape gets the same signature whatever the spacing', () => {
  assert.equal(signatureOf([' Item Code', 'Description']), signatureOf(['item code', 'DESCRIPTION']));
  assert.notEqual(signatureOf(['Item Code']), signatureOf(['Item Code', 'Pack']));
});
