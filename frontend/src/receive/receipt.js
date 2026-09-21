import { daysBetween, parseExpiry, thaiDate, toSatang, uuid4 } from '../format.js';

// One receiving document (ใบรับยา) being entered. Quantities and costs stay as
// the text the user typed; they're checked and converted when saving.
export function newReceipt(today) {
  return {
    id: null,
    status: 'draft',
    isOpening: false,
    supplierId: '',
    invoiceNo: '',
    invoiceDate: '',
    receivedDate: today,
    note: '',
    lines: [],
    createdBy: '',
    postedBy: '',
    postedAt: null,
    dirty: false,
  };
}

const defaultUnitId = (product) => (product.units.find((u) => u.is_default) || product.units[0]).id;

export const lineUnit = (line) => line.product.units.find((u) => u.id === line.unitId) || line.product.units[0];

const costText = (value) => (value === undefined || value === null ? '' : String(value));

export function receiptReducer(state, action) {
  switch (action.type) {
    case 'set':
      return { ...state, ...action.fields, dirty: true };
    case 'add': {
      const unitId = action.unitId || defaultUnitId(action.product);
      const last = state.lines[state.lines.length - 1];
      // Scanning the same box again before its lot is filled in just counts it.
      if (last && last.unitId === unitId && !last.lotNo.trim()) {
        return {
          ...state,
          dirty: true,
          lines: state.lines.map((l) => (l === last ? { ...l, qty: String((Number(l.qty) || 0) + 1) } : l)),
        };
      }
      const line = {
        key: uuid4(),
        product: action.product,
        unitId,
        qty: '1',
        lotNo: '',
        expiryText: '',
        unitCost: '',
        lastCosts: {},
      };
      return { ...state, dirty: true, lines: [...state.lines, line] };
    }
    case 'lastCosts':
      // Prefill the cost from the last delivery, unless someone already typed one.
      return {
        ...state,
        lines: state.lines.map((l) =>
          l.product.id === action.productId
            ? { ...l, lastCosts: action.costs, unitCost: l.unitCost === '' ? costText(action.costs[l.unitId]) : l.unitCost }
            : l,
        ),
      };
    case 'update':
      return {
        ...state,
        dirty: true,
        lines: state.lines.map((l) => {
          if (l.key !== action.key) return l;
          const next = { ...l, ...action.changes };
          // Switching unit (box ↔ strip) swaps in that unit's last cost if the cost wasn't edited.
          if ('unitId' in action.changes && l.unitCost === costText(l.lastCosts[l.unitId])) {
            next.unitCost = costText(l.lastCosts[action.changes.unitId]);
          }
          return next;
        }),
      };
    case 'remove':
      return { ...state, dirty: true, lines: state.lines.filter((l) => l.key !== action.key) };
    case 'load':
      return fromServer(action.purchase);
    case 'reset':
      return newReceipt(action.today);
    default:
      return state;
  }
}

export function fromServer(p) {
  return {
    id: p.id,
    status: p.status,
    isOpening: p.is_opening_balance,
    supplierId: p.supplier_id ? String(p.supplier_id) : '',
    invoiceNo: p.invoice_no,
    invoiceDate: p.invoice_date || '',
    receivedDate: p.received_date,
    note: p.note,
    createdBy: p.created_by,
    postedBy: p.posted_by,
    postedAt: p.posted_at,
    dirty: false,
    lines: p.items.map((item) => ({
      key: uuid4(),
      product: item.product,
      unitId: item.unit_id,
      qty: String(item.qty),
      lotNo: item.lot_no,
      expiryText: item.expiry_date ? thaiDate(item.expiry_date) : '',
      unitCost: costText(item.unit_cost),
      lastCosts: {},
    })),
  };
}

const isWholeNumber = (text) => /^\d+$/.test(String(text).trim()) && Number(text) > 0;
const isMoney = (text) => /^\d+(\.\d{1,2})?$/.test(String(text).trim());

export const lineTotalSatang = (line) =>
  isWholeNumber(line.qty) && isMoney(line.unitCost) ? Number(line.qty) * toSatang(line.unitCost) : 0;

export const receiptTotalSatang = (r) => r.lines.reduce((sum, line) => sum + lineTotalSatang(line), 0);

// Warnings are shown while typing; errors block posting to stock.
export function checkLine(line, receipt, nearExpiryDays) {
  const errors = [];
  const warnings = [];
  if (!isWholeNumber(line.qty)) errors.push('จำนวนต้องเป็นจำนวนเต็มมากกว่า 0');
  if (!line.lotNo.trim()) errors.push('กรอกเลขที่ lot');
  const expiry = parseExpiry(line.expiryText);
  if (!line.expiryText.trim()) {
    errors.push('กรอกวันหมดอายุ');
  } else if (expiry.error) {
    errors.push(expiry.error);
  } else if (receipt.receivedDate) {
    const days = daysBetween(receipt.receivedDate, expiry.iso);
    if (days <= 0) {
      if (receipt.isOpening) warnings.push('หมดอายุแล้ว (ยอดยกมารับได้ แต่ขายไม่ได้)');
      else errors.push('หมดอายุแล้ว รับเข้าไม่ได้');
    } else if (days <= nearExpiryDays) {
      warnings.push(`ใกล้หมดอายุ (อีก ${days} วัน)`);
    }
    // Same lot number already in stock with another expiry is almost always a typo.
    const known = line.product.lots?.find((lot) => lot.lot_no === line.lotNo.trim());
    if (known && known.expiry_date !== expiry.iso) {
      warnings.push(`lot ${known.lot_no} ในสต็อกหมดอายุ ${thaiDate(known.expiry_date)} — ตรวจอีกครั้ง`);
    }
  }
  if (line.unitCost.trim() === '') {
    if (!receipt.isOpening) errors.push('กรอกราคาทุน (ของแถมใส่ 0)');
  } else if (!isMoney(line.unitCost)) {
    errors.push('ราคาทุนไม่ถูกต้อง');
  }
  return { errors, warnings };
}

export function checkReceipt(r, { today, nearExpiryDays }) {
  const errors = [];
  if (!r.isOpening && !r.supplierId) errors.push('เลือกผู้ขาย');
  if (!r.receivedDate) errors.push('กรอกวันที่รับยา');
  else if (r.receivedDate > today) errors.push('วันที่รับยาเป็นวันในอนาคต');
  if (!r.lines.length) errors.push('ยังไม่มีรายการยา');
  const lines = Object.fromEntries(r.lines.map((line) => [line.key, checkLine(line, r, nearExpiryDays)]));
  const badLines = r.lines.filter((line) => lines[line.key].errors.length).length;
  if (badLines) errors.push(`มี ${badLines} รายการที่ยังกรอกไม่ครบหรือไม่ถูกต้อง`);
  return { ok: errors.length === 0, errors, lines };
}

// A draft may be incomplete, but a date or number we can't read would be lost on save.
export function draftProblems(r) {
  const problems = [];
  if (!r.receivedDate) problems.push('กรอกวันที่รับยา');
  r.lines.forEach((line, i) => {
    if (!isWholeNumber(line.qty)) problems.push(`รายการที่ ${i + 1}: จำนวนไม่ถูกต้อง`);
    if (line.expiryText.trim() && parseExpiry(line.expiryText).error) problems.push(`รายการที่ ${i + 1}: อ่านวันหมดอายุไม่ออก`);
    if (line.unitCost.trim() && !isMoney(line.unitCost)) problems.push(`รายการที่ ${i + 1}: ราคาทุนไม่ถูกต้อง`);
  });
  return problems;
}

export function receiptPayload(r, post) {
  return {
    received_date: r.receivedDate,
    is_opening_balance: r.isOpening,
    supplier_id: r.supplierId ? Number(r.supplierId) : null,
    invoice_no: r.invoiceNo.trim(),
    invoice_date: r.invoiceDate || null,
    note: r.note.trim(),
    post,
    lines: r.lines.map((line) => ({
      unit_id: line.unitId,
      qty: Number(line.qty),
      lot_no: line.lotNo.trim(),
      expiry_date: parseExpiry(line.expiryText).iso,
      // Empty stays empty (not yet entered) — only a typed 0 means free goods.
      unit_cost: line.unitCost.trim() === '' ? null : (toSatang(line.unitCost) / 100).toFixed(2),
    })),
  };
}
