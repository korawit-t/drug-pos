import { toSatang, uuid4 } from '../format.js';

// One drug being added or edited by hand. Numbers stay as the text that was
// typed and are checked before saving; the server checks them again.
export function blankUnit() {
  return { key: uuid4(), id: null, name: '', factor: '1', barcode: '', isDefault: false, prices: ['', '', '', '', ''] };
}

export function blankDrug() {
  return {
    id: null,
    code: '',
    tradeName: '',
    genericName: '',
    strength: '',
    dosageForm: '',
    category: '',
    baseUnit: '',
    registrationNo: '',
    inKy11: false,
    inKy13: false,
    defaultDosage: '',
    labelWarning: '',
    storageLocation: '',
    isActive: true,
    allergenIds: [],
    matchedAllergens: '',
    onHand: 0,
    units: [blankUnit()],
    dirty: false,
  };
}

const text = (value) => (value === null || value === undefined ? '' : String(value));

export function fromServer(p) {
  return {
    ...blankDrug(),
    id: p.id,
    code: p.code,
    tradeName: p.trade_name,
    genericName: p.generic_name,
    strength: p.strength,
    dosageForm: p.dosage_form,
    category: p.category,
    baseUnit: p.base_unit,
    registrationNo: p.registration_no,
    inKy11: p.in_ky11_list,
    inKy13: p.in_ky13_list,
    defaultDosage: p.default_dosage,
    labelWarning: p.label_warning,
    storageLocation: p.storage_location,
    isActive: p.is_active,
    allergenIds: p.allergen_ids,
    matchedAllergens: p.matched_allergens,
    onHand: p.on_hand,
    units: p.units.map((u) => ({
      key: uuid4(),
      id: u.id,
      name: u.name,
      factor: String(u.factor),
      barcode: u.barcode,
      isDefault: u.is_default,
      prices: u.prices.map(text),
    })),
    dirty: false,
  };
}

export function drugReducer(state, action) {
  switch (action.type) {
    case 'set':
      return { ...state, ...action.fields, dirty: true };
    case 'addUnit':
      return { ...state, dirty: true, units: [...state.units, blankUnit()] };
    case 'updateUnit':
      return {
        ...state,
        dirty: true,
        units: state.units.map((u) => (u.key === action.key ? { ...u, ...action.changes } : u)),
      };
    case 'price':
      return {
        ...state,
        dirty: true,
        units: state.units.map((u) =>
          u.key === action.key ? { ...u, prices: u.prices.map((p, i) => (i === action.level ? action.value : p)) } : u,
        ),
      };
    case 'defaultUnit':
      return {
        ...state,
        dirty: true,
        units: state.units.map((u) => ({ ...u, isDefault: u.key === action.key })),
      };
    case 'removeUnit':
      return state.units.length < 2
        ? state
        : { ...state, dirty: true, units: state.units.filter((u) => u.key !== action.key) };
    case 'load':
      return fromServer(action.product);
    case 'reset':
      return blankDrug();
    default:
      return state;
  }
}

const isWholeNumber = (value) => /^\d+$/.test(value.trim()) && Number(value) > 0;
const isMoney = (value) => /^\d+(\.\d{1,2})?$/.test(value.trim());

export function checkUnit(unit, drug) {
  const errors = [];
  if (!unit.name.trim()) errors.push('ใส่ชื่อหน่วย');
  if (!isWholeNumber(unit.factor)) errors.push(`${drug.baseUnit || 'หน่วยเล็กสุด'}ต่อหน่วยนี้ต้องเป็นจำนวนเต็มตั้งแต่ 1`);
  if (!unit.prices[0].trim()) errors.push('ใส่ราคาระดับ 1');
  else if (!isMoney(unit.prices[0])) errors.push('ราคาระดับ 1 ไม่ถูกต้อง');
  unit.prices.slice(1).forEach((price, index) => {
    if (price.trim() && !isMoney(price)) errors.push(`ราคาระดับ ${index + 2} ไม่ถูกต้อง`);
  });
  return { errors };
}

export function checkDrug(drug) {
  const errors = [];
  if (!drug.tradeName.trim()) errors.push('ใส่ชื่อการค้า');
  if (!drug.baseUnit.trim()) errors.push('ใส่หน่วยเล็กสุด (หน่วยที่ใช้นับสต็อก)');
  if (!drug.category) errors.push('เลือกประเภทยา');

  const names = new Map();
  const barcodes = new Map();
  for (const unit of drug.units) {
    const name = unit.name.trim().toLowerCase();
    if (name && names.has(name)) errors.push(`หน่วย ${unit.name.trim()} ซ้ำกัน`);
    if (name) names.set(name, unit.key);
    const barcode = unit.barcode.trim();
    if (barcode && barcodes.has(barcode)) errors.push(`บาร์โค้ด ${barcode} ซ้ำกัน`);
    if (barcode) barcodes.set(barcode, unit.key);
  }
  const units = Object.fromEntries(drug.units.map((unit) => [unit.key, checkUnit(unit, drug)]));
  const badUnits = drug.units.filter((unit) => units[unit.key].errors.length).length;
  if (badUnits) errors.push(`มีหน่วยขาย ${badUnits} หน่วยที่กรอกไม่ครบ`);
  return { ok: errors.length === 0, errors, units };
}

// Keeps empty price levels empty: an empty level falls back to level 1, a 0 would sell it free.
const price = (value) => (value.trim() === '' ? null : (toSatang(value) / 100).toFixed(2));

export function drugPayload(drug) {
  const defaultKey = (drug.units.find((u) => u.isDefault) || drug.units[0])?.key;
  return {
    code: drug.code.trim(),
    trade_name: drug.tradeName.trim(),
    generic_name: drug.genericName.trim(),
    strength: drug.strength.trim(),
    dosage_form: drug.dosageForm.trim(),
    category: drug.category,
    base_unit: drug.baseUnit.trim(),
    registration_no: drug.registrationNo.trim(),
    in_ky11_list: drug.inKy11,
    in_ky13_list: drug.inKy13,
    default_dosage: drug.defaultDosage.trim(),
    label_warning: drug.labelWarning.trim(),
    storage_location: drug.storageLocation.trim(),
    is_active: drug.isActive,
    allergen_ids: drug.allergenIds,
    units: drug.units.map((unit) => ({
      id: unit.id,
      name: unit.name.trim(),
      factor: Number(unit.factor),
      barcode: unit.barcode.trim(),
      is_default: unit.key === defaultKey,
      prices: unit.prices.map(price),
    })),
  };
}
