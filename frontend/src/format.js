// Money is handled in satang (integers) on the client so totals never drift.
export const toSatang = (value) => Math.round(Number(value) * 100);

export const baht = (satang) =>
  (satang / 100).toLocaleString('th-TH', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const bahtOf = (decimalString) => baht(toSatang(decimalString));

// Dates arrive as ISO strings (ค.ศ.); people read พ.ศ.
export function thaiDate(iso, style = 'short') {
  if (!iso) return '';
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  const year = y + 543;
  if (style === 'month') return `${String(m).padStart(2, '0')}/${year}`;
  return `${String(d).padStart(2, '0')}/${String(m).padStart(2, '0')}/${year}`;
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
