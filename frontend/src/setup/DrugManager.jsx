import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { api } from '../api.js';
import { submitOnEnter } from '../pos/ui.jsx';
import { blankDrug, checkDrug, drugPayload, drugReducer } from './drugs.js';

// Scanning straight into the list: one box per selling unit that hasn't got a
// barcode yet, so the shop can walk the shelf and shoot each box in turn.
function ScanRow({ row, onScan, inputRef }) {
  const [values, setValues] = useState({});
  const missing = row.units.filter((unit) => !unit.barcode);
  return (
    // คลิกหรือยิงบาร์โค้ดในแถบนี้ไม่ควรไปเปิดฟอร์มแก้ไขของแถวนั้น
    <div className="scan-row" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
      {missing.map((unit, index) => (
        <label key={unit.id} className="field-inline">
          <span className="muted small">{unit.name}</span>
          <input
            ref={index === 0 ? inputRef : undefined}
            value={values[unit.id] ?? ''}
            placeholder="ยิงบาร์โค้ดที่นี่"
            aria-label={`บาร์โค้ดของ ${row.display_name} หน่วย ${unit.name}`}
            autoComplete="off"
            onChange={(e) => setValues({ ...values, [unit.id]: e.target.value.trim() })}
            onKeyDown={submitOnEnter(() => {
              const code = (values[unit.id] || '').trim();
              if (code) onScan(unit.id, code);
            })}
          />
        </label>
      ))}
    </div>
  );
}

function UnitRow({ unit, index, issues, showErrors, levels, dispatch, onlyOne }) {
  const update = (changes) => dispatch({ type: 'updateUnit', key: unit.key, changes });
  return (
    <tr>
      <td className="col-no">{index + 1}</td>
      <td className="col-unit-name">
        <input
          value={unit.name}
          placeholder="แผง"
          aria-label={`ชื่อหน่วยขายที่ ${index + 1}`}
          onChange={(e) => update({ name: e.target.value })}
        />
        {showErrors &&
          issues.errors.map((e) => (
            <div key={e} className="line-error">
              {e}
            </div>
          ))}
      </td>
      <td className="col-qty">
        <input
          inputMode="numeric"
          value={unit.factor}
          aria-label={`จำนวนหน่วยเล็กสุดต่อหน่วยขายที่ ${index + 1}`}
          onChange={(e) => update({ factor: e.target.value.replace(/\D/g, '') })}
        />
      </td>
      <td className="col-lot">
        <input
          value={unit.barcode}
          placeholder="สแกนได้"
          aria-label={`บาร์โค้ดของหน่วยขายที่ ${index + 1}`}
          onChange={(e) => update({ barcode: e.target.value.trim() })}
        />
      </td>
      {levels.map((level, i) => (
        <td key={level.level} className="col-price">
          <input
            inputMode="decimal"
            value={unit.prices[i]}
            placeholder={i === 0 ? 'บังคับ' : 'ใช้ราคา 1'}
            aria-label={`ราคาระดับ ${level.level} ของหน่วยขายที่ ${index + 1}`}
            onChange={(e) => dispatch({ type: 'price', key: unit.key, level: i, value: e.target.value.replace(/[^\d.]/g, '') })}
          />
        </td>
      ))}
      <td className="col-default">
        <input
          type="radio"
          name="default-unit"
          checked={unit.isDefault}
          aria-label={`ให้หน่วยขายที่ ${index + 1} เป็นหน่วยหลัก`}
          onChange={() => dispatch({ type: 'defaultUnit', key: unit.key })}
        />
      </td>
      <td className="col-del">
        {!onlyOne && (
          <button
            type="button"
            className="icon-btn"
            aria-label={`ลบหน่วยขายที่ ${index + 1}`}
            onClick={() => dispatch({ type: 'removeUnit', key: unit.key })}
          >
            ×
          </button>
        )}
      </td>
    </tr>
  );
}

function DrugForm({ drug, dispatch, meta, allergens, busy, showErrors, check, onSave, onCancel }) {
  const set = (fields) => dispatch({ type: 'set', fields });
  const levels = meta.price_levels;
  const toggleAllergen = (id) =>
    set({ allergenIds: drug.allergenIds.includes(id) ? drug.allergenIds.filter((a) => a !== id) : [...drug.allergenIds, id] });

  return (
    <div className="panel">
      <div className="receipt-title">
        <h2>{drug.id ? `แก้ไข ${drug.tradeName || 'ยา'}` : 'เพิ่มยาใหม่'}</h2>
        {drug.id > 0 && (
          <span className="muted small">
            คงเหลือ {drug.onHand.toLocaleString('th-TH')} {drug.baseUnit}
          </span>
        )}
        {drug.dirty && <span className="muted small">ยังไม่ได้บันทึก</span>}
      </div>

      <fieldset className="head-grid">
        <label className="field">
          ชื่อการค้า *
          <input value={drug.tradeName} onChange={(e) => set({ tradeName: e.target.value })} />
        </label>
        <label className="field">
          ความแรง
          <input value={drug.strength} placeholder="500 mg" onChange={(e) => set({ strength: e.target.value })} />
        </label>
        <label className="field">
          ชื่อสามัญ
          <input
            value={drug.genericName}
            placeholder="ใช้จับคู่กลุ่มยาแพ้"
            onChange={(e) => set({ genericName: e.target.value })}
          />
        </label>
        <label className="field">
          ประเภท *
          <select value={drug.category} onChange={(e) => set({ category: e.target.value })}>
            <option value="">— เลือก —</option>
            {meta.categories.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          หน่วยเล็กสุด (ใช้นับสต็อก) *
          <input value={drug.baseUnit} placeholder="เม็ด" onChange={(e) => set({ baseUnit: e.target.value })} />
        </label>
        <label className="field">
          รูปแบบยา
          <input value={drug.dosageForm} placeholder="เม็ด / น้ำเชื่อม" onChange={(e) => set({ dosageForm: e.target.value })} />
        </label>
        <label className="field">
          รหัสสินค้า
          <input value={drug.code} placeholder="ของร้าน/โปรแกรมเดิม" onChange={(e) => set({ code: e.target.value })} />
        </label>
        <label className="field">
          ที่เก็บ
          <input value={drug.storageLocation} placeholder="ชั้น A1" onChange={(e) => set({ storageLocation: e.target.value })} />
        </label>
        <label className="field">
          เลขทะเบียนตำรับ
          <input value={drug.registrationNo} onChange={(e) => set({ registrationNo: e.target.value })} />
        </label>
        <label className="field span-all">
          วิธีใช้ (ขึ้นบนฉลาก)
          <input
            value={drug.defaultDosage}
            placeholder="รับประทานครั้งละ 1 เม็ด วันละ 3 ครั้ง หลังอาหาร"
            onChange={(e) => set({ defaultDosage: e.target.value })}
          />
        </label>
        <label className="field span-all">
          คำเตือนบนฉลาก
          <input value={drug.labelWarning} onChange={(e) => set({ labelWarning: e.target.value })} />
        </label>
        <div className="field span-all check-row">
          <label className="check">
            <input type="checkbox" checked={drug.inKy11} onChange={(e) => set({ inKy11: e.target.checked })} />
            ต้องลงบัญชี ขย.11 (ถามชื่อผู้ซื้อตอนขาย)
          </label>
          <label className="check">
            <input type="checkbox" checked={drug.inKy13} onChange={(e) => set({ inKy13: e.target.checked })} />
            ต้องรายงาน ขย.13
          </label>
          <label className="check">
            <input type="checkbox" checked={drug.isActive} onChange={(e) => set({ isActive: e.target.checked })} />
            ใช้งาน (ปิดเพื่อซ่อนจากหน้าขาย)
          </label>
        </div>
      </fieldset>

      <div className="field">
        กลุ่มยาสำหรับแจ้งเตือนแพ้ยา
        {drug.matchedAllergens && <span className="muted small"> · ระบบจับคู่จากชื่อได้: {drug.matchedAllergens}</span>}
        <div className="chip-row">
          {allergens.map((a) => (
            <button
              type="button"
              key={a.id}
              className={`chip ${drug.allergenIds.includes(a.id) ? 'active' : ''}`}
              aria-pressed={drug.allergenIds.includes(a.id)}
              onClick={() => toggleAllergen(a.id)}
            >
              {a.name}
            </button>
          ))}
        </div>
        <p className="muted small">เลือกเพิ่มเมื่อชื่อยาไม่บอกกลุ่ม เช่น ยาชื่อการค้าที่ไม่มีชื่อสามัญ</p>
      </div>

      <div className="field">
        หน่วยขายและราคา
        <table className="cart receive-table unit-table">
          <thead>
            <tr>
              <th className="col-no">#</th>
              <th className="col-unit-name">หน่วยขาย</th>
              <th className="col-qty">{drug.baseUnit || 'หน่วยเล็กสุด'}/หน่วย</th>
              <th className="col-lot">บาร์โค้ด</th>
              {levels.map((level) => (
                <th key={level.level} className="col-price">
                  {level.level} · {level.name}
                </th>
              ))}
              <th className="col-default">หลัก</th>
              <th className="col-del" aria-label="ลบ" />
            </tr>
          </thead>
          <tbody>
            {drug.units.map((unit, index) => (
              <UnitRow
                key={unit.key}
                unit={unit}
                index={index}
                issues={check.units[unit.key]}
                showErrors={showErrors}
                levels={levels}
                dispatch={dispatch}
                onlyOne={drug.units.length < 2}
              />
            ))}
          </tbody>
        </table>
        <button type="button" className="btn small" onClick={() => dispatch({ type: 'addUnit' })}>
          + เพิ่มหน่วยขาย
        </button>
        <p className="muted small">
          ราคาระดับ 2–5 เว้นว่างได้ = ใช้ราคาระดับ 1 · อย่าใส่ 0 ถ้าไม่ได้ตั้งใจขายฟรี
        </p>
      </div>

      {showErrors && check.errors.length > 0 && <div className="alert danger">{check.errors.join(' · ')}</div>}

      <div className="row-actions">
        <button type="button" className="btn" onClick={onCancel}>
          ยกเลิก
        </button>
        <button type="button" className="btn primary" disabled={busy} onClick={onSave}>
          {busy ? 'กำลังบันทึก…' : drug.id ? 'บันทึกการแก้ไข' : 'เพิ่มยานี้'}
        </button>
      </div>
    </div>
  );
}

// "ทีละรายการ": add a drug by hand, or find one and fix it — the other half of
// importing a file, and what the shop needs right after one (categories, prices).
export default function DrugManager({ meta, notify }) {
  const [drug, dispatch] = useReducer(drugReducer, undefined, blankDrug);
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('');
  const [gaps, setGaps] = useState([]);
  const [rows, setRows] = useState(null);
  const scanRef = useRef(null);
  const [allergens, setAllergens] = useState([]);
  const [editing, setEditing] = useState(false);
  const [showErrors, setShowErrors] = useState(false);
  const [busy, setBusy] = useState(false);

  const search = useCallback(
    async (text, missing) => {
      try {
        const [found, summary] = await Promise.all([
          api('/manage/products', { params: { q: text, missing: missing || '' } }),
          api('/manage/gaps'),
        ]);
        setRows(found);
        setGaps(summary);
      } catch (err) {
        notify(err.message, 'error');
      }
    },
    [notify],
  );

  useEffect(() => {
    search('', '');
    api('/allergens')
      .then(setAllergens)
      .catch(() => setAllergens([]));
  }, [search]);

  function show(text, missing) {
    setQuery(text);
    setFilter(missing);
    search(text, missing);
  }

  async function acceptSuggestion(row) {
    try {
      await api(`/manage/products/${row.id}/category`, { method: 'PUT', body: { category: row.suggestion.category } });
      notify(`${row.display_name}: ตั้งเป็น ${row.suggestion.label} แล้ว`);
      search(query, filter);
    } catch (err) {
      notify(err.message, 'error');
    }
  }

  async function saveBarcode(unitId, barcode) {
    try {
      await api(`/manage/units/${unitId}/barcode`, { method: 'PUT', body: { barcode } });
      await search(query, filter);
      setTimeout(() => scanRef.current?.focus(), 0); // ยิงตัวถัดไปต่อได้เลย
    } catch (err) {
      notify(err.message, 'error');
    }
  }

  const check = useMemo(() => checkDrug(drug), [drug]);
  const discardOk = () => !drug.dirty || window.confirm('ทิ้งข้อมูลที่ยังไม่ได้บันทึก?');

  async function openDrug(id) {
    if (!discardOk()) return;
    try {
      dispatch({ type: 'load', product: await api(`/manage/products/${id}`) });
      setEditing(true);
      setShowErrors(false);
    } catch (err) {
      notify(err.message, 'error');
    }
  }

  function startNew() {
    if (!discardOk()) return;
    dispatch({ type: 'reset' });
    setEditing(true);
    setShowErrors(false);
  }

  async function save() {
    if (!check.ok) {
      setShowErrors(true);
      notify(check.errors[0], 'error');
      return;
    }
    setBusy(true);
    try {
      const saved = await api(drug.id ? `/manage/products/${drug.id}` : '/manage/products', {
        method: drug.id ? 'PUT' : 'POST',
        body: drugPayload(drug),
      });
      dispatch({ type: 'load', product: saved });
      notify(`บันทึก ${saved.trade_name} ${saved.strength} แล้ว`.trim());
      search(query, filter);
    } catch (err) {
      notify(err.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="panel">
        <div className="receipt-title">
          <h2>เพิ่มหรือแก้ไขยาทีละรายการ</h2>
          <button type="button" className="btn primary small" onClick={startNew}>
            + เพิ่มยาใหม่
          </button>
        </div>
        <p className="muted small">
          ใช้ตอนรับยาตัวใหม่เข้าร้าน หรือตามไปแก้ยาที่เพิ่งนำเข้าจากไฟล์ เช่น ตั้งประเภทยาให้ถูกและเติมชื่อสามัญ
        </p>
        <label className="field">
          ค้นหา (ชื่อยา ชื่อสามัญ รหัสสินค้า หรือบาร์โค้ด)
          <input
            value={query}
            placeholder="พิมพ์เพื่อค้นหา — เว้นว่างคือทั้งหมด"
            onChange={(e) => show(e.target.value, filter)}
          />
        </label>

        <div className="field">
          ข้อมูลที่ยังไม่ครบ
          <div className="chip-row">
            <button
              type="button"
              className={`chip ${filter === '' ? 'active' : ''}`}
              aria-pressed={filter === ''}
              onClick={() => show(query, '')}
            >
              ทั้งหมด
            </button>
            {gaps.map((gap) => (
              <button
                type="button"
                key={gap.key}
                className={`chip ${filter === gap.key ? 'active' : ''} ${gap.count ? '' : 'done'}`}
                aria-pressed={filter === gap.key}
                title={gap.why}
                disabled={!gap.count && filter !== gap.key}
                onClick={() => show(query, gap.key)}
              >
                {gap.label} {gap.count.toLocaleString('th-TH')}
              </button>
            ))}
          </div>
          {filter === 'barcode' && (
            <p className="muted small">
              ยิงบาร์โค้ดลงช่องในแต่ละแถวได้เลย กด <kbd>Enter</kbd> แล้วระบบจะเลื่อนไปตัวถัดไปให้เอง
            </p>
          )}
          {filter === 'review' && (
            <p className="muted small">
              ยาพวกนี้มาจากไฟล์ที่ไม่ได้บอกประเภท ระบบเดาแทนไว้ก่อน — <strong>เภสัชกรต้องเป็นคนยืนยัน</strong>{' '}
              ข้อเสนอที่ขึ้นเป็นแค่การจับคำจากชื่อยา ไม่ใช่การจัดประเภทตามกฎหมาย
            </p>
          )}
        </div>
        {rows === null ? (
          <p className="muted small">กำลังโหลด…</p>
        ) : rows.length === 0 ? (
          <p className="muted small">{filter ? 'เรื่องนี้ครบหมดแล้ว' : 'ไม่พบยาที่ตรงกับคำค้น'}</p>
        ) : (
          <ul className="pick-list drug-list">
            {rows.map((row) => (
              <li
                key={row.id}
                className={row.id === drug.id ? 'active' : ''}
                role="button"
                tabIndex={0}
                onClick={() => openDrug(row.id)}
                onKeyDown={(e) => e.key === 'Enter' && openDrug(row.id)}
              >
                <div className="drug-row">
                  <strong>{row.display_name}</strong>
                  {!row.is_active && <span className="badge neutral small">ปิดใช้งาน</span>}
                  {row.missing.includes('review') && <span className="badge amber small">ยังไม่ได้ตรวจประเภท</span>}
                  <div className="muted small">
                    {row.code && `${row.code} · `}
                    {row.generic_name && `${row.generic_name} · `}
                    {row.category_label} · {row.unit_count} หน่วยขาย · คงเหลือ {row.on_hand.toLocaleString('th-TH')}{' '}
                    {row.base_unit}
                  </div>
                  {filter === 'barcode' && (
                    <ScanRow
                      row={row}
                      onScan={saveBarcode}
                      inputRef={row.id === rows[0]?.id ? scanRef : undefined}
                    />
                  )}
                  {filter === 'review' && row.suggestion && (
                    <div className="suggestion" onClick={(e) => e.stopPropagation()}>
                      <span>
                        เดาจากคำว่า "{row.suggestion.term}" ในชื่อยา — น่าจะเป็น <strong>{row.suggestion.label}</strong>
                      </span>
                      <button type="button" className="btn small" onClick={() => acceptSuggestion(row)}>
                        ใช่ ตั้งตามนี้
                      </button>
                    </div>
                  )}
                  {filter === 'review' && !row.suggestion && (
                    <div className="muted small">ชื่อยาไม่บอกตัวยา — ต้องเปิดดูแล้วเลือกประเภทเอง</div>
                  )}
                </div>
                <span className="muted small">แก้ไข</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {editing && (
        <DrugForm
          drug={drug}
          dispatch={dispatch}
          meta={meta}
          allergens={allergens}
          busy={busy}
          showErrors={showErrors}
          check={check}
          onSave={save}
          onCancel={() => {
            if (!discardOk()) return;
            setEditing(false);
            dispatch({ type: 'reset' });
          }}
        />
      )}
    </>
  );
}
