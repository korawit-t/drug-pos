import assert from 'node:assert/strict';
import { test } from 'node:test';
import { billNeeds, billReducer, checkoutPayload, newBill } from './bill.js';

const amox = { id: 1, needs_pharmacist: true, default_dosage: '', units: [{ id: 10, factor: 10, is_default: true, prices: ['40'] }], lots: [] };
const para = { id: 2, needs_pharmacist: false, default_dosage: '', units: [{ id: 20, factor: 10, is_default: true, prices: ['15'] }], lots: [] };
const alice = { id: 7, price_level: 2 };

function billWith(...actions) {
  return actions.reduce(billReducer, newBill());
}

test('a household remedy needs the pharmacist once it matches an allergy', () => {
  const bill = billWith({ type: 'add', product: para });
  assert.equal(billNeeds(bill).pending.length, 0);
  assert.equal(billNeeds(bill, { 2: [{ level: 'direct' }] }).pending.length, 1);
});

test('an approval without the allergy acknowledged is dropped when an alert appears', () => {
  let bill = billWith({ type: 'add', product: amox }, { type: 'setCustomer', customer: alice });
  const key = bill.lines[0].key;
  bill = billReducer(bill, { type: 'approve', tokens: { [key]: 't1' }, pharmacistName: 'ภก.ก', customerId: 7 });
  assert.ok(bill.lines[0].approval);
  bill = billReducer(bill, { type: 'syncAllergyApprovals', productIds: [1], customerId: 7 });
  assert.equal(bill.lines[0].approval, null);
});

test('an acknowledged allergy survives a re-check for the same customer only', () => {
  let bill = billWith({ type: 'add', product: amox }, { type: 'setCustomer', customer: alice });
  const key = bill.lines[0].key;
  bill = billReducer(bill, {
    type: 'approve', tokens: { [key]: 't1' }, pharmacistName: 'ภก.ก', customerId: 7,
    allergyKeys: [key], notes: { [key]: 'เคยใช้แล้วไม่แพ้' },
  });
  assert.equal(bill.lines[0].allergyNote, 'เคยใช้แล้วไม่แพ้');
  assert.equal(checkoutPayload(bill, { method: 'transfer' }).lines[0].allergy_note, 'เคยใช้แล้วไม่แพ้');
  assert.ok(billReducer(bill, { type: 'syncAllergyApprovals', productIds: [1], customerId: 7 }).lines[0].approval);
  assert.equal(billReducer(bill, { type: 'syncAllergyApprovals', productIds: [1], customerId: 8 }).lines[0].approval, null);
});

test('refreshing the customer keeps the price level chosen for the bill', () => {
  let bill = billWith({ type: 'setCustomer', customer: alice }, { type: 'setPriceLevel', level: 4 });
  bill = billReducer(bill, { type: 'updateCustomer', customer: { ...alice, allergies: [{ id: 1 }] } });
  assert.equal(bill.priceLevel, 4);
  assert.equal(bill.customer.allergies.length, 1);
});
