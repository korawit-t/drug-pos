import { uuid4 } from '../format.js';

// One stock count sheet (ใบนับสต็อก) being entered. One line per lot, because
// stock lives in lots. Numbers stay as typed text and are checked when saving.
export function newSheet(today) {
  return {
    id: null,
    status: 'draft',
    countedDate: today,
    note: '',
    lines: [],
    createdBy: '',
    postedBy: '',
    approvedBy: '',
    postedAt: null,
    dirty: false,
  };
}

function newLine(lot) {
  return {
    key: uuid4(),
    lot,
    systemQty: lot.qty, // what the person counting saw — the server checks it hasn't moved
    factor: 1, // counting unit: 1 = หน่วยเล็กสุด, otherwise a pack size
    qtyText: '',
    looseText: '', // loose base units on top of whole packs (3 กล่อง กับอีก 7 เม็ด)
    diffText: null, // set while the difference column is being typed into
    reason: '',
    note: '',
    stale: false, // the system quantity changed after this line was entered
  };
}

const isCount = (text) => /^\d+$/.test(String(text).trim());
const isDifference = (text) => /^[+-]?\d+$/.test(String(text).trim());

// null: nothing typed yet · NaN: typed something we can't read
export function countedQty(line) {
  const qty = line.qtyText.trim();
  const loose = line.looseText.trim();
  if (qty === '' && loose === '') return null;
  if ((qty !== '' && !isCount(qty)) || (loose !== '' && !isCount(loose))) return NaN;
  return (qty === '' ? 0 : Number(qty)) * line.factor + (loose === '' ? 0 : Number(loose));
}

export function difference(line) {
  const counted = countedQty(line);
  return counted === null || Number.isNaN(counted) ? null : counted - line.systemQty;
}

export const isCounted = (line) => Number.isInteger(countedQty(line));

// The difference column is the same number seen from the other side: typing
// "-5" there (ของแตก 5 เม็ด) fills in the counted quantity, and the other way round.
function fromDifference(line, text) {
  const next = { ...line, diffText: text };
  if (!isDifference(text)) return next;
  const target = line.systemQty + Number(text);
  return { ...next, factor: 1, looseText: '', qtyText: target < 0 ? '' : String(target) };
}

export function sheetReducer(state, action) {
  switch (action.type) {
    case 'set':
      return { ...state, ...action.fields, dirty: true };
    case 'add': {
      // prefill: ยาหมดอายุที่ทิ้งไปแล้วมักนับได้ 0 ทุกแถว — เติมให้ล่วงหน้าแต่ยังแก้ได้
      const known = new Set(state.lines.map((l) => l.lot.id));
      const added = action.lots
        .filter((lot) => !known.has(lot.id))
        .map((lot) => ({ ...newLine(lot), ...action.prefill }));
      if (!added.length) return state;
      return { ...state, dirty: true, lines: [...state.lines, ...added] };
    }
    case 'update':
      return {
        ...state,
        dirty: true,
        lines: state.lines.map((l) => (l.key === action.key ? { ...l, ...action.changes, diffText: null } : l)),
      };
    case 'difference':
      return {
        ...state,
        dirty: true,
        lines: state.lines.map((l) => (l.key === action.key ? fromDifference(l, action.text) : l)),
      };
    case 'remove':
      return { ...state, dirty: true, lines: state.lines.filter((l) => l.key !== action.key) };
    case 'refresh': {
      // Pull today's quantities in again: what was counted stays, but any line
      // whose system quantity moved is flagged so it gets checked once more.
      const fresh = new Map(action.lots.map((lot) => [lot.id, lot]));
      return {
        ...state,
        lines: state.lines.map((l) => {
          const lot = fresh.get(l.lot.id);
          if (!lot || lot.qty === l.systemQty) return l;
          return { ...l, lot, systemQty: lot.qty, stale: true, diffText: null };
        }),
      };
    }
    case 'load':
      return fromServer(action.count);
    case 'reset':
      return newSheet(action.today);
    default:
      return state;
  }
}

export function fromServer(c) {
  return {
    id: c.id,
    status: c.status,
    countedDate: c.counted_date,
    note: c.note,
    createdBy: c.created_by,
    postedBy: c.posted_by,
    approvedBy: c.approved_by,
    postedAt: c.posted_at,
    dirty: false,
    lines: c.items.map((item) => ({
      ...newLine(item.lot),
      // A reopened draft shows the count in base units; how it was keyed in (packs
      // plus loose) isn't worth storing.
      systemQty: item.system_qty,
      qtyText: item.counted_qty === null ? '' : String(item.counted_qty),
      reason: item.reason,
      note: item.note,
      // On a posted sheet the lot has moved *because* of this adjustment — only a
      // draft that stock has moved under needs checking again.
      stale: c.status === 'draft' && item.lot.qty !== item.system_qty,
    })),
  };
}

// Warnings are shown while typing; errors block the adjustment.
export function checkLine(line) {
  const errors = [];
  const warnings = [];
  const counted = countedQty(line);
  if (Number.isNaN(counted)) {
    errors.push('จำนวนที่นับได้ต้องเป็นจำนวนเต็ม');
  } else if (line.diffText !== null && !isDifference(line.diffText)) {
    errors.push('ส่วนต่างต้องเป็นจำนวนเต็ม เช่น -5');
  } else if (counted === null) {
    if (line.diffText !== null && isDifference(line.diffText)) {
      errors.push(`ตัดออกได้มากที่สุด ${line.systemQty}`);
    } else {
      errors.push('ยังไม่ได้นับรายการนี้');
    }
  } else {
    const diff = counted - line.systemQty;
    if (diff !== 0 && !line.reason) errors.push('เลือกสาเหตุที่ยอดไม่ตรง');
    if (line.reason === 'other' && !line.note.trim()) errors.push('เลือก "อื่น ๆ" ต้องเขียนหมายเหตุด้วย');
    if (line.lot.expired && counted > 0) warnings.push('ยาหมดอายุแล้ว ขายไม่ได้ — ถ้าทิ้งไปแล้วให้ใส่ 0');
  }
  if (line.stale) {
    warnings.push(`ยอดในระบบเปลี่ยนเป็น ${line.systemQty} ${line.lot.base_unit} ระหว่างนับ — ตรวจอีกครั้ง`);
  }
  return { errors, warnings };
}

export function checkSheet(sheet, { today }) {
  const errors = [];
  if (!sheet.countedDate) errors.push('กรอกวันที่นับ');
  else if (sheet.countedDate > today) errors.push('วันที่นับเป็นวันในอนาคต');
  if (!sheet.lines.length) errors.push('ยังไม่มีรายการ');
  const lines = Object.fromEntries(sheet.lines.map((line) => [line.key, checkLine(line)]));
  const badLines = sheet.lines.filter((line) => lines[line.key].errors.length).length;
  if (badLines) errors.push(`มี ${badLines} รายการที่ยังนับไม่ครบหรือกรอกไม่ถูกต้อง`);
  return { ok: errors.length === 0, errors, lines };
}

// A draft may be half-counted, but a number we can't read would be lost on save.
export function draftProblems(sheet) {
  const problems = [];
  if (!sheet.countedDate) problems.push('กรอกวันที่นับ');
  sheet.lines.forEach((line, i) => {
    if (Number.isNaN(countedQty(line))) problems.push(`รายการที่ ${i + 1}: จำนวนที่นับได้ไม่ถูกต้อง`);
  });
  return problems;
}

export function sheetSummary(sheet) {
  let counted = 0;
  let shortage = 0;
  let surplus = 0;
  let differing = 0;
  for (const line of sheet.lines) {
    if (!isCounted(line)) continue;
    counted += 1;
    const diff = difference(line);
    if (diff < 0) shortage += -diff;
    if (diff > 0) surplus += diff;
    if (diff !== 0) differing += 1;
  }
  return { lines: sheet.lines.length, counted, uncounted: sheet.lines.length - counted, shortage, surplus, differing };
}

export function sheetPayload(sheet, post, approval = {}) {
  return {
    counted_date: sheet.countedDate,
    note: sheet.note.trim(),
    post,
    pharmacist_id: approval.pharmacistId ?? null,
    pin: approval.pin ?? '',
    lines: sheet.lines.map((line) => {
      const counted = countedQty(line);
      return {
        lot_id: line.lot.id,
        system_qty: line.systemQty,
        counted_qty: Number.isInteger(counted) ? counted : null,
        reason: line.reason,
        note: line.note.trim(),
      };
    }),
  };
}
