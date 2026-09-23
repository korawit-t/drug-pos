import { baht, thaiDate } from '../format.js';
import { AllergyList, CategoryBadge } from './ui.jsx';

function CustomerCard({ bill, meta, dispatch, onPickCustomer, onAddAllergy }) {
  const c = bill.customer;
  return (
    <section className="panel">
      <div className="panel-head">
        <h3>ลูกค้า</h3>
        <button type="button" className="btn small" onClick={onPickCustomer}>
          เลือกลูกค้า <kbd>F2</kbd>
        </button>
      </div>
      <div className="customer-name">{c ? c.name : 'ลูกค้าทั่วไป'}</div>
      {c && c.phone && <div className="muted small">{c.phone}</div>}
      {c && (
        <div className={`alert ${c.allergies.length ? 'danger' : 'info'}`}>
          <div className="alert-head">
            <strong>{c.allergies.length ? 'แพ้ยา' : 'ไม่มีประวัติแพ้ยาในระบบ'}</strong>
            <button type="button" className="btn small" onClick={onAddAllergy}>
              + บันทึกแพ้ยา
            </button>
          </div>
          {c.allergies.length > 0 && <AllergyList allergies={c.allergies} />}
        </div>
      )}
      {c && c.chronic_conditions && (
        <div className="alert warning">
          <strong>โรคประจำตัว:</strong> {c.chronic_conditions}
        </div>
      )}
      <label className="field-inline">
        ระดับราคา
        <select
          value={bill.priceLevel}
          onChange={(e) => dispatch({ type: 'setPriceLevel', level: Number(e.target.value) })}
        >
          {meta.price_levels.map((p) => (
            <option key={p.level} value={p.level}>
              {p.level} · {p.name}
            </option>
          ))}
        </select>
      </label>
      <label className="check">
        <input
          type="checkbox"
          checked={bill.isPrescription}
          onChange={(e) => dispatch({ type: 'setFields', fields: { isPrescription: e.target.checked } })}
        />
        ขายตามใบสั่งยา (ลง ขย.12)
      </label>
    </section>
  );
}

function SelectedLine({ line, dispatch }) {
  if (!line) {
    return (
      <section className="panel">
        <h3>รายการที่เลือก</h3>
        <p className="muted small">คลิกรายการในบิลเพื่อดูรายละเอียดและแก้วิธีใช้บนฉลาก</p>
      </section>
    );
  }
  const p = line.product;
  return (
    <section className="panel">
      <h3>รายการที่เลือก</h3>
      <div className="line-name">
        {p.display_name} <CategoryBadge product={p} />
      </div>
      <div className="muted small">
        {[p.generic_name, p.dosage_form, p.storage_location && `ที่เก็บ ${p.storage_location}`].filter(Boolean).join(' · ')}
      </div>
      <div className="small">
        คงเหลือ {p.available} {p.base_unit}
        {p.lots.length > 0 && (
          <span className="muted">
            {' '}
            ({p.lots.map((l) => `${l.lot_no} หมด ${thaiDate(l.expiry_date, 'month')}: ${l.qty}`).join(', ')})
          </span>
        )}
      </div>
      {p.category !== 'general' && (
        <label className="field">
          วิธีใช้ (พิมพ์ลงฉลาก)
          <textarea
            rows={2}
            value={line.dosage}
            onChange={(e) => dispatch({ type: 'update', key: line.key, changes: { dosage: e.target.value } })}
          />
          {p.label_warning && <span className="muted small">คำเตือนบนฉลาก: {p.label_warning}</span>}
        </label>
      )}
    </section>
  );
}

export default function SidePanel({
  bill,
  meta,
  totalSatang,
  dispatch,
  onPickCustomer,
  onAddAllergy,
  onPay,
  printPrefs,
  setPrintPrefs,
}) {
  const selected = bill.lines.find((l) => l.key === bill.selectedKey);
  const count = bill.lines.length;
  return (
    <aside className="side">
      <div className="side-scroll">
        <CustomerCard
          bill={bill}
          meta={meta}
          dispatch={dispatch}
          onPickCustomer={onPickCustomer}
          onAddAllergy={onAddAllergy}
        />
        <SelectedLine line={selected} dispatch={dispatch} />
      </div>
      <section className="panel total-panel">
        <div className="total-row">
          <span className="muted">{count} รายการ</span>
          <span className="total">{baht(totalSatang)}</span>
        </div>
        <button type="button" className="btn primary big" onClick={onPay} disabled={count === 0}>
          ชำระเงิน <kbd>F12</kbd>
        </button>
        <div className="print-prefs">
          <label className="check">
            <input
              type="checkbox"
              checked={printPrefs.receipt}
              onChange={(e) => setPrintPrefs({ ...printPrefs, receipt: e.target.checked })}
            />
            พิมพ์ใบเสร็จทันที
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={printPrefs.labels}
              onChange={(e) => setPrintPrefs({ ...printPrefs, labels: e.target.checked })}
            />
            พิมพ์ฉลากยาทันที
          </label>
        </div>
      </section>
    </aside>
  );
}
