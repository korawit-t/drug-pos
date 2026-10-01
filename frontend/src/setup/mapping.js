// Matching the columns of someone else's file to the fields we need.
// A field belongs to at most one column, and a column holds at most one field.

export function fieldAt(mapping, index) {
  const found = Object.entries(mapping).find(([, column]) => column === index);
  return found ? found[0] : '';
}

// Picking a field for a column takes it away from whichever column had it.
export function assign(mapping, index, field) {
  const next = Object.fromEntries(Object.entries(mapping).filter(([name, column]) => column !== index && name !== field));
  if (field) next[field] = index;
  return next;
}

export const missingRequired = (mapping, fields) =>
  fields.filter((field) => field.required && !(field.name in mapping));

export const mappedCount = (mapping) => Object.keys(mapping).length;

// The same program exports the same shape every time, so remembering the match
// by the file's own column names saves doing it again next month.
export const signatureOf = (headers) => headers.map((h) => h.trim().toLowerCase()).join('|');

const STORE = 'drugpos.columnMaps';

function readStore() {
  try {
    return JSON.parse(localStorage.getItem(STORE) || '{}');
  } catch {
    return {};
  }
}

export function rememberMapping(headers, mapping) {
  try {
    const store = readStore();
    store[signatureOf(headers)] = mapping;
    localStorage.setItem(STORE, JSON.stringify(store));
  } catch {
    // private mode or storage disabled — the match just won't be remembered
  }
}

export const recallMapping = (headers) => readStore()[signatureOf(headers)] || null;
