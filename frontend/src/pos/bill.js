import { toSatang, uuid4 } from '../format.js';

// One bill at the counter. `clientUuid` identifies it to the server: pharmacist
// confirmations are signed for this bill, and checkout is safe to retry.
export function newBill() {
  return {
    clientUuid: uuid4(),
    lines: [],
    selectedKey: null,
    customer: null,
    priceLevel: 1,
    buyerName: '',
    isPrescription: false,
    rx: { prescriber: '', license: '', facility: '', date: '' },
  };
}

export const lineUnit = (line) => line.product.units.find((u) => u.id === line.unitId) || line.product.units[0];
export const unitPriceSatang = (line, level) => toSatang(lineUnit(line).prices[level - 1]);
export const lineTotalSatang = (line, level) => unitPriceSatang(line, level) * line.qty;
export const baseQty = (line) => line.qty * lineUnit(line).factor;
export const billTotalSatang = (bill) =>
  bill.lines.reduce((sum, line) => sum + lineTotalSatang(line, bill.priceLevel), 0);

function defaultUnitId(product, matchedUnitId) {
  if (matchedUnitId) return matchedUnitId;
  return (product.units.find((u) => u.is_default) || product.units[0]).id;
}

// Anything the pharmacist signed off on — unit, quantity, label text, and the
// reason for dispensing despite an allergy. Changing one means confirming again.
const APPROVED_FIELDS = ['unitId', 'qty', 'dosage', 'allergyNote'];

export function billReducer(state, action) {
  switch (action.type) {
    case 'add': {
      const unitId = defaultUnitId(action.product, action.unitId);
      const existing = state.lines.find((l) => l.product.id === action.product.id && l.unitId === unitId);
      if (existing) {
        return {
          ...state,
          selectedKey: existing.key,
          lines: state.lines.map((l) =>
            l.key === existing.key ? { ...l, product: action.product, qty: l.qty + 1, approval: null } : l,
          ),
        };
      }
      const line = {
        key: uuid4(),
        product: action.product,
        unitId,
        qty: 1,
        dosage: action.product.default_dosage || '',
        allergyNote: '',
        approval: null,
      };
      return { ...state, lines: [...state.lines, line], selectedKey: line.key };
    }
    case 'update':
      return {
        ...state,
        lines: state.lines.map((l) => {
          if (l.key !== action.key) return l;
          const touched = APPROVED_FIELDS.some((f) => f in action.changes && action.changes[f] !== l[f]);
          return { ...l, ...action.changes, approval: touched ? null : l.approval };
        }),
      };
    case 'remove': {
      const index = state.lines.findIndex((l) => l.key === action.key);
      const lines = state.lines.filter((l) => l.key !== action.key);
      const neighbour = lines[Math.min(index, lines.length - 1)];
      return { ...state, lines, selectedKey: neighbour ? neighbour.key : null };
    }
    case 'select':
      return { ...state, selectedKey: action.key };
    case 'moveSelection': {
      if (!state.lines.length) return state;
      const index = state.lines.findIndex((l) => l.key === state.selectedKey);
      const next = Math.max(0, Math.min(state.lines.length - 1, (index < 0 ? 0 : index) + action.delta));
      return { ...state, selectedKey: state.lines[next].key };
    }
    case 'setCustomer':
      return { ...state, customer: action.customer, priceLevel: action.customer ? action.customer.price_level : 1 };
    case 'updateCustomer':
      // Same customer, fresh details (e.g. an allergy was just recorded) — keep the bill's price level.
      return state.customer && state.customer.id === action.customer.id ? { ...state, customer: action.customer } : state;
    case 'setPriceLevel':
      return { ...state, priceLevel: action.level };
    case 'setFields':
      return { ...state, ...action.fields };
    case 'approve': {
      const allergyKeys = new Set(action.allergyKeys || []);
      return {
        ...state,
        lines: state.lines.map((l) => {
          if (!action.tokens[l.key]) return l;
          const allergyAck = allergyKeys.has(l.key);
          return {
            ...l,
            allergyNote: allergyAck ? action.notes?.[l.key] ?? '' : l.allergyNote,
            approval: {
              token: action.tokens[l.key],
              by: action.pharmacistName,
              allergyAck,
              customerId: action.customerId ?? null,
            },
          };
        }),
      };
    }
    case 'syncAllergyApprovals': {
      // A confirmation only covers an allergy the pharmacist actually saw, for this customer.
      const alerted = new Set(action.productIds);
      return {
        ...state,
        lines: state.lines.map((l) =>
          l.approval && alerted.has(l.product.id) && !(l.approval.allergyAck && l.approval.customerId === action.customerId)
            ? { ...l, approval: null }
            : l,
        ),
      };
    }
    case 'clearApprovals':
      return { ...state, lines: state.lines.map((l) => ({ ...l, approval: null })) };
    case 'reset':
      return newBill();
    case 'load':
      return action.bill;
    default:
      return state;
  }
}

// FEFO preview: which lots each line will probably come from. The server makes
// the real allocation at checkout; this is just so the counter sees it early.
export function planStock(lines) {
  const remaining = new Map();
  const plan = {};
  for (const line of lines) {
    const id = line.product.id;
    if (!remaining.has(id)) remaining.set(id, line.product.lots.map((lot) => ({ ...lot })));
    let need = baseQty(line);
    const allocations = [];
    for (const lot of remaining.get(id)) {
      if (need === 0) break;
      const take = Math.min(lot.qty, need);
      if (take > 0) {
        allocations.push({ lot_no: lot.lot_no, expiry_date: lot.expiry_date, qty: take });
        lot.qty -= take;
        need -= take;
      }
    }
    plan[line.key] = { allocations, short: need };
  }
  return plan;
}

// alerts: allergy alerts per product id for the bill's customer.
export const lineAlerts = (line, alerts) => alerts?.[line.product.id] || [];

export const needsPharmacist = (line, alerts) => line.product.needs_pharmacist || lineAlerts(line, alerts).length > 0;

export function billNeeds(bill, alerts = {}) {
  return {
    pending: bill.lines.filter((l) => needsPharmacist(l, alerts) && !l.approval),
    needsBuyer: bill.lines.some((l) => l.product.needs_buyer_name),
    needsRx: bill.isPrescription || bill.lines.some((l) => l.product.needs_prescription),
  };
}

export function checkoutPayload(bill, { method, cashReceived }) {
  return {
    client_uuid: bill.clientUuid,
    payment_method: method,
    cash_received: method === 'cash' ? cashReceived : null,
    price_level: bill.priceLevel,
    customer_id: bill.customer ? bill.customer.id : null,
    buyer_name: bill.buyerName,
    is_prescription: bill.isPrescription,
    rx_prescriber: bill.rx.prescriber,
    rx_prescriber_license: bill.rx.license,
    rx_facility: bill.rx.facility,
    rx_date: bill.rx.date || null,
    lines: bill.lines.map((l) => ({
      unit_id: l.unitId,
      qty: l.qty,
      dosage_text: l.dosage.trim(),
      approval: l.approval ? l.approval.token : null,
      allergy_note: l.allergyNote || '',
    })),
  };
}

export function heldPayload(bill) {
  return {
    lines: bill.lines.map((l) => ({ productId: l.product.id, unitId: l.unitId, qty: l.qty, dosage: l.dosage })),
    customer: bill.customer,
    priceLevel: bill.priceLevel,
    buyerName: bill.buyerName,
    isPrescription: bill.isPrescription,
    rx: bill.rx,
  };
}

// A resumed bill is a new bill: fresh prices and stock, and the pharmacist confirms again.
export function billFromHeld(payload, products) {
  const byId = new Map(products.map((p) => [p.id, p]));
  const lines = payload.lines
    .filter((l) => byId.has(l.productId))
    .map((l) => ({
      key: uuid4(),
      product: byId.get(l.productId),
      unitId: l.unitId,
      qty: l.qty,
      dosage: l.dosage,
      allergyNote: '',
      approval: null,
    }));
  return {
    ...newBill(),
    lines,
    selectedKey: lines[0] ? lines[0].key : null,
    customer: payload.customer,
    priceLevel: payload.priceLevel,
    buyerName: payload.buyerName,
    isPrescription: payload.isPrescription,
    rx: payload.rx,
  };
}
