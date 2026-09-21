// Money is handled in satang (integers) on the client so totals never drift.
export const toSatang = (value) => Math.round(Number(value) * 100);

export const baht = (satang) =>
  (satang / 100).toLocaleString('th-TH', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const bahtOf = (decimalString) => baht(toSatang(decimalString));

const THAI_MONTHS = ['ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.'];

// Dates arrive as ISO strings (ค.ศ.); people read พ.ศ.
// short: 21/09/2569 · month: 09/2569 · long: 21 ก.ย. 2569
export function thaiDate(iso, style = 'short') {
  if (!iso) return '';
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  const year = y + 543;
  if (style === 'month') return `${String(m).padStart(2, '0')}/${year}`;
  if (style === 'long') return `${d} ${THAI_MONTHS[m - 1]} ${year}`;
  return `${String(d).padStart(2, '0')}/${String(m).padStart(2, '0')}/${year}`;
}

const pad2 = (n) => String(n).padStart(2, '0');

// Two-digit years: 60–99 are พ.ศ. (2560–2599), 00–59 are ค.ศ. (2000–2059).
// Drug expiry dates fall within a few years of today, so the ranges never overlap.
function expandYear(text) {
  if (text.length === 2) {
    const yy = Number(text);
    return yy >= 60 ? 2500 + yy : 2000 + yy;
  }
  return text.length === 4 ? Number(text) : null;
}

export const EXPIRY_HINT = 'พิมพ์ได้ เช่น 03/2028, 03/71, 31/03/2571';

// Expiry dates typed the way they're printed on the box. A month-only date
// ("03/2028") means the end of that month. พ.ศ. years are converted to ค.ศ.
// Returns { iso, error }; both null for an empty field.
export function parseExpiry(text) {
  const raw = (text || '').trim();
  if (!raw) return { iso: null, error: null };
  let day = null;
  let month;
  let year;
  const iso = raw.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (iso) {
    [year, month, day] = iso.slice(1).map(Number);
  } else {
    const parts = raw.split(/[/.\-\s]+/);
    if (!parts.every((p) => /^\d+$/.test(p)) || parts.length < 2 || parts.length > 3) {
      return { iso: null, error: EXPIRY_HINT };
    }
    if (parts.length === 3) day = Number(parts[0]);
    month = Number(parts[parts.length - 2]);
    year = expandYear(parts[parts.length - 1]);
  }
  if (year === null) return { iso: null, error: EXPIRY_HINT };
  if (year > 2400) year -= 543;
  if (year < 2000 || year > 2100) return { iso: null, error: 'ปีไม่ถูกต้อง' };
  if (month < 1 || month > 12) return { iso: null, error: 'เดือนไม่ถูกต้อง' };
  const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
  if (day === null) day = lastDay;
  if (day < 1 || day > lastDay) return { iso: null, error: 'วันที่ไม่ถูกต้อง' };
  return { iso: `${year}-${pad2(month)}-${pad2(day)}`, error: null };
}

// Date inputs are ค.ศ.; if someone types a พ.ศ. year (e.g. 2569), convert it.
export function toGregorianDate(iso) {
  if (!iso) return iso;
  const year = Number(iso.slice(0, 4));
  return year > 2400 ? `${year - 543}${iso.slice(4)}` : iso;
}

export const timeOf = (isoDateTime) =>
  new Date(isoDateTime).toLocaleTimeString('th-TH', { hour: '2-digit', minute: '2-digit' });

export function daysBetween(fromIso, toIso) {
  const utc = (iso) => {
    const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
    return Date.UTC(y, m - 1, d);
  };
  return Math.round((utc(toIso) - utc(fromIso)) / 86400000);
}

// crypto.randomUUID only exists on https/localhost; the shop LAN is plain http.
export function uuid4() {
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = [...b].map((x) => x.toString(16).padStart(2, '0')).join('');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}
