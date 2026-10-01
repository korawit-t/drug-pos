import assert from 'node:assert/strict';
import { test } from 'node:test';
import { blankDrug, checkDrug, drugPayload, drugReducer, fromServer } from './drugs.js';

const filled = (over = {}) => ({
  ...blankDrug(),
  tradeName: 'Ibuprofen',
  strength: '400 mg',
  baseUnit: 'เม็ด',
  category: 'dangerous',
  ...over,
});

function withUnit(drug, changes) {
  return drugReducer(drug, { type: 'updateUnit', key: drug.units[0].key, changes });
}

test('a drug needs a name, a base unit, a category and a priced unit', () => {
  const empty = blankDrug();
  const problems = checkDrug(empty).errors.join(' ');
  assert.match(problems, /ชื่อการค้า/);
  assert.match(problems, /หน่วยเล็กสุด/);
  assert.match(problems, /ประเภทยา/);

  let drug = filled();
  assert.match(checkDrug(drug).errors.join(), /กรอกไม่ครบ/);
  drug = withUnit(drug, { name: 'แผง', factor: '10' });
  assert.match(checkDrug(drug).units[drug.units[0].key].errors.join(), /ราคาระดับ 1/);

  drug = drugReducer(drug, { type: 'price', key: drug.units[0].key, level: 0, value: '40' });
  assert.equal(checkDrug(drug).ok, true);
});

test('empty price levels stay empty so they fall back to level 1', () => {
  let drug = withUnit(filled(), { name: 'แผง', factor: '10' });
  drug = drugReducer(drug, { type: 'price', key: drug.units[0].key, level: 0, value: '40' });
  drug = drugReducer(drug, { type: 'price', key: drug.units[0].key, level: 1, value: '38.50' });
  const payload = drugPayload(drug);
  assert.deepEqual(payload.units[0].prices, ['40.00', '38.50', null, null, null]);
  assert.equal(payload.units[0].is_default, true); // หน่วยแรกเป็นหน่วยหลักถ้าไม่ได้เลือก
  assert.equal(payload.trade_name, 'Ibuprofen');
});

test('a second unit can be added and one of them is the default', () => {
  let drug = withUnit(filled(), { name: 'แผง', factor: '10' });
  drug = drugReducer(drug, { type: 'price', key: drug.units[0].key, level: 0, value: '40' });
  drug = drugReducer(drug, { type: 'addUnit' });
  const second = drug.units[1];
  drug = drugReducer(drug, { type: 'updateUnit', key: second.key, changes: { name: 'กล่อง', factor: '100' } });
  drug = drugReducer(drug, { type: 'price', key: second.key, level: 0, value: '380' });
  drug = drugReducer(drug, { type: 'defaultUnit', key: second.key });

  assert.equal(checkDrug(drug).ok, true);
  const payload = drugPayload(drug);
  assert.deepEqual(payload.units.map((u) => [u.name, u.factor, u.is_default]), [
    ['แผง', 10, false],
    ['กล่อง', 100, true],
  ]);
});

test('duplicate unit names and barcodes are caught before saving', () => {
  let drug = withUnit(filled(), { name: 'แผง', factor: '10', barcode: '200042' });
  drug = drugReducer(drug, { type: 'price', key: drug.units[0].key, level: 0, value: '40' });
  drug = drugReducer(drug, { type: 'addUnit' });
  const second = drug.units[1];
  drug = drugReducer(drug, { type: 'updateUnit', key: second.key, changes: { name: 'แผง', barcode: '200042' } });
  drug = drugReducer(drug, { type: 'price', key: second.key, level: 0, value: '40' });
  const problems = checkDrug(drug).errors.join(' ');
  assert.match(problems, /หน่วย แผง ซ้ำกัน/);
  assert.match(problems, /บาร์โค้ด 200042 ซ้ำกัน/);
});

test('the last unit cannot be removed', () => {
  const drug = withUnit(filled(), { name: 'แผง' });
  const after = drugReducer(drug, { type: 'removeUnit', key: drug.units[0].key });
  assert.equal(after.units.length, 1);
});

test('a drug loaded for editing comes back with its units and no unsaved flag', () => {
  const drug = fromServer({
    id: 7,
    code: 'IBU-400',
    trade_name: 'Ibuprofen',
    generic_name: 'Ibuprofen',
    strength: '400 mg',
    dosage_form: 'เม็ด',
    category: 'dangerous',
    base_unit: 'เม็ด',
    registration_no: '',
    in_ky11_list: true,
    in_ky13_list: false,
    default_dosage: '',
    label_warning: '',
    storage_location: 'ชั้น A1',
    is_active: true,
    allergen_ids: [3],
    matched_allergens: 'NSAIDs',
    on_hand: 120,
    units: [{ id: 2, name: 'แผง', factor: 10, barcode: '', is_default: true, prices: ['40.00', null, null, null, null] }],
  });
  assert.equal(drug.dirty, false);
  assert.equal(drug.inKy11, true);
  assert.equal(drug.onHand, 120);
  assert.deepEqual(drug.units[0].prices, ['40.00', '', '', '', '']);
  assert.equal(checkDrug(drug).ok, true);
  assert.equal(drugPayload(drug).units[0].id, 2); // แก้หน่วยเดิม ไม่ใช่สร้างใหม่
});
