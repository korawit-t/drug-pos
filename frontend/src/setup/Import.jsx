import { useRef, useState } from 'react';
import { upload } from '../api.js';
import { Brand, TopLinks, ViewTabs } from '../nav.jsx';
import { Modal, Toast, useToast } from '../pos/ui.jsx';
import ColumnMapper from './ColumnMapper.jsx';
import DrugManager from './DrugManager.jsx';
import { missingRequired, recallMapping, rememberMapping } from './mapping.js';

function Summary({ result }) {
  const cards = [
    ['ยาใหม่', result.products_created],
    ['ยาที่อัปเดต', result.products_updated],
    ['หน่วยขายใหม่', result.units_created],
    ['หน่วยขายที่อัปเดต', result.units_updated],
    ['รายการยอดยกมา', result.stock_lines],
    ['ใช้ประเภทเริ่มต้น', result.default_category_rows],
  ];
  return (
    <div className="summary-cards">
      {cards.map(([label, value]) => (
        <div key={label} className="summary-card">
          <div className="muted small">{label}</div>
          <div className="summary-value">{value.toLocaleString('th-TH')}</div>
        </div>
      ))}
    </div>
  );
}

function Issues({ title, issues, total, kind }) {
  if (!total) return null;
  return (
    <div className={`issues ${kind}`}>
      <strong>
        {title} {total.toLocaleString('th-TH')} รายการ
        {issues.length < total && ` (แสดง ${issues.length} รายการแรก)`}
      </strong>
      <ul>
        {issues.map((issue, i) => (
          <li key={`${issue.row}-${i}`}>
            {issue.row > 0 ? `แถวที่ ${issue.row}: ` : ''}
            {issue.message}
          </li>
        ))}
      </ul>
    </div>
  );
}

// Setup screen: fill in the shop's drug list in Excel, check it, then import.
export default function ImportData({ meta, nav, active }) {
  const [tab, setTab] = useState('file');
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [mapping, setMapping] = useState({});
  const [headerRow, setHeaderRow] = useState(1);
  const [withStock, setWithStock] = useState(false);
  const [defaultCategory, setDefaultCategory] = useState('');
  const [result, setResult] = useState(null);
  const [checkedKey, setCheckedKey] = useState('');
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toast, notify] = useToast();
  const inputRef = useRef(null);

  const key = file
    ? `${file.name}|${file.size}|${file.lastModified}|${withStock}|${defaultCategory}|${headerRow}|${JSON.stringify(mapping)}`
    : '';
  const checked = key !== '' && checkedKey === key && result;
  const unmatched = preview ? missingRequired(mapping, preview.fields) : [];
  const readyToImport = checked && !result.error_count && !result.committed;

  async function inspect(nextFile, row) {
    const body = new FormData();
    body.append('file', nextFile);
    if (row) body.append('header_row', String(row));
    const data = await upload('/import/inspect', body);
    setPreview(data);
    setHeaderRow(data.header_row);
    // ถ้าเคยจับคู่ไฟล์หน้าตาเดียวกันไว้แล้ว ใช้ของเดิม ไม่ต้องทำซ้ำทุกเดือน
    setMapping(recallMapping(data.headers) || data.guess);
    return data;
  }

  async function pickFile(nextFile) {
    setFile(nextFile);
    setResult(null);
    setCheckedKey('');
    setPreview(null);
    setMapping({});
    if (!nextFile) return;
    setBusy(true);
    try {
      await inspect(nextFile, null);
    } catch (err) {
      notify(err.message, 'error');
      setFile(null);
      if (inputRef.current) inputRef.current.value = '';
    } finally {
      setBusy(false);
    }
  }

  async function changeHeaderRow(row) {
    setHeaderRow(row);
    setResult(null);
    setCheckedKey('');
    setBusy(true);
    try {
      await inspect(file, row);
    } catch (err) {
      notify(err.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  async function send(commit) {
    if (!file) {
      notify('เลือกไฟล์ก่อน', 'error');
      return;
    }
    const body = new FormData();
    body.append('file', file);
    body.append('with_stock', withStock ? 'true' : 'false');
    body.append('commit', commit ? 'true' : 'false');
    body.append('default_category', defaultCategory);
    body.append('mapping', JSON.stringify(mapping));
    body.append('header_row', String(headerRow));
    setBusy(true);
    setConfirming(false);
    try {
      const data = await upload('/import/products', body);
      setResult(data);
      setCheckedKey(key);
      if (data.committed) {
        notify(`นำเข้าแล้ว ${data.rows.toLocaleString('th-TH')} แถว`);
        if (preview) rememberMapping(preview.headers, mapping);
        if (inputRef.current) inputRef.current.value = '';
        setFile(null);
        setPreview(null);
      } else if (data.error_count) {
        notify(`พบข้อผิดพลาด ${data.error_count} รายการ — ยังไม่ได้บันทึกอะไร`, 'error');
      } else if (!commit) {
        notify('ไฟล์ผ่านการตรวจแล้ว');
      }
    } catch (err) {
      setResult(null);
      setCheckedKey('');
      notify(err.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="pos setup" hidden={!active}>
      <header className="topbar">
        <Brand name={meta.shop.name} />
        <ViewTabs nav={nav} />
        <TopLinks nav={nav} />
      </header>

      <main className="setup-main">
        <div className="setup-tabs" role="tablist" aria-label="วิธีเพิ่มข้อมูลยา">
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'file'}
            className={`btn ${tab === 'file' ? 'primary' : ''}`}
            onClick={() => setTab('file')}
          >
            นำเข้าจากไฟล์ Excel / CSV
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'manual'}
            className={`btn ${tab === 'manual' ? 'primary' : ''}`}
            onClick={() => setTab('manual')}
          >
            เพิ่ม / แก้ไขทีละรายการ
          </button>
        </div>

        {tab === 'manual' && <DrugManager meta={meta} notify={notify} />}

        <div className="panel" hidden={tab !== 'file'}>
          <h2>นำเข้าข้อมูลยาจาก Excel</h2>
          <ol className="steps">
            <li>
              <a className="btn" href="/api/import/template" download>
                ดาวน์โหลดไฟล์ตัวอย่าง (.xlsx)
              </a>
              <span className="muted small"> มีชีต "คำอธิบาย" บอกทุกคอลัมน์</span>
            </li>
            <li>
              กรอกข้อมูลยา <strong>1 แถว = 1 หน่วยขาย</strong> — ยาตัวเดียวกันขายทั้งเม็ด แผง และกล่อง ให้ใส่ 3 แถว
              ใช้ชื่อการค้าและความแรงเดียวกัน
            </li>
            <li>เลือกไฟล์ → ตรวจไฟล์ → นำเข้า (ถ้ามีแถวผิดแม้แถวเดียว ระบบจะไม่บันทึกอะไรเลย)</li>
          </ol>
          <p className="muted small">
            นำเข้าซ้ำได้ ระบบจับคู่ด้วยรหัสสินค้า บาร์โค้ด หรือชื่อการค้า + ความแรง แล้วอัปเดตให้ จึงใช้ปรับราคาทั้งร้านได้ด้วย
          </p>
          <p className="muted small">
            ใช้ไฟล์ที่ส่งออกจากโปรแกรมเดิมได้เลย ระบบหาหัวตารางเองแม้มีบรรทัดชื่อรายงานอยู่ข้างบน ตัดบรรทัดสรุปท้ายไฟล์ออกให้
            และรู้จักชื่อคอลัมน์แบบไทยทั่วไป (ชื่อสินค้า, วันที่หมดอายุ, จำนวนเหลือ, ต้นทุน/หน่วย, ราคาระดับ 1–5)
          </p>
        </div>

        <div className="panel" hidden={tab !== 'file'}>
          <label className="field">
            ไฟล์ข้อมูล (.xlsx หรือ .csv)
            <input
              ref={inputRef}
              type="file"
              accept=".xlsx,.csv,text/csv"
              onChange={(e) => pickFile(e.target.files[0] || null)}
            />
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={withStock}
              onChange={(e) => {
                setWithStock(e.target.checked);
                setCheckedKey('');
              }}
            />
            นำเข้ายอดยกมาด้วย (ช่องยอดยกมา, lot, วันหมดอายุ)
          </label>
          <label className="field">
            ประเภทยาเริ่มต้น (ใช้เมื่อไฟล์ไม่มีคอลัมน์ "ประเภท")
            <select
              value={defaultCategory}
              onChange={(e) => {
                setDefaultCategory(e.target.value);
                setCheckedKey('');
              }}
            >
              <option value="">— ไม่ตั้ง: ไฟล์ต้องบอกประเภทเอง —</option>
              {meta.categories.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
          {defaultCategory && (
            <div className="alert warning">
              ยาใหม่ที่ไฟล์ไม่ได้บอกประเภทจะถูกตั้งเป็น <strong>{meta.categories.find((c) => c.value === defaultCategory)?.label}</strong> ทั้งหมด —
              ประเภทเป็นตัวตัดสินว่าขายแล้วต้องให้เภสัชกรยืนยันหรือไม่ นำเข้าเสร็จแล้วให้ไปตรวจทีละตัวที่แท็บ "เพิ่ม / แก้ไขทีละรายการ"
            </div>
          )}
          {withStock && (
            <div className="alert warning">
              ยอดยกมาจะถูก <strong>บวกเพิ่ม</strong> เข้าสต็อกทุกครั้งที่นำเข้า ถ้านำเข้าไฟล์เดิมซ้ำ สต็อกจะเกิน —
              ใช้ตอนเริ่มใช้ระบบครั้งแรกครั้งเดียว
            </div>
          )}
          <div className="row-actions">
            <button
              type="button"
              className="btn"
              disabled={busy || !file || unmatched.length > 0}
              onClick={() => send(false)}
            >
              {busy ? 'กำลังตรวจ…' : 'ตรวจไฟล์'}
            </button>
            <button
              type="button"
              className="btn primary"
              disabled={busy || !readyToImport}
              onClick={() => setConfirming(true)}
            >
              นำเข้าจริง
            </button>
          </div>
          {file && !checked && <p className="muted small">กด "ตรวจไฟล์" ก่อน ระบบจะบอกว่าจะเพิ่มหรือแก้อะไรบ้าง</p>}
        </div>

        {preview && tab === 'file' && (
          <ColumnMapper
            preview={preview}
            mapping={mapping}
            busy={busy}
            onChange={(next) => {
              setMapping(next);
              setCheckedKey('');
            }}
            onHeaderRow={changeHeaderRow}
          />
        )}

        {result && tab === 'file' && (
          <div className="panel">
            <div
              className={`alert ${result.committed ? 'success' : result.error_count ? 'danger' : 'warning'}`}
            >
              {result.committed
                ? `นำเข้าเรียบร้อย ${result.rows.toLocaleString('th-TH')} แถว`
                : result.error_count
                  ? 'พบข้อผิดพลาด — ยังไม่มีการบันทึกใด ๆ แก้ไฟล์แล้วตรวจใหม่'
                  : `ไฟล์ผ่านการตรวจ ${result.rows.toLocaleString('th-TH')} แถว — ยังไม่ได้บันทึก กด "นำเข้าจริง" เพื่อบันทึก`}
            </div>
            <Summary result={result} />
            {result.columns.length > 0 && (
              <p className="muted small">อ่านหัวตารางได้ {result.columns.length} คอลัมน์: {result.columns.join(', ')}</p>
            )}
            {result.stock_lines > 0 && (
              <p className="muted small">
                ยอดยกมารวม {result.stock_base_qty.toLocaleString('th-TH')} หน่วยเล็กสุด
                {result.committed ? ' เข้าสต็อกแล้ว' : ' (จะเข้าสต็อกเมื่อนำเข้าจริง)'}
              </p>
            )}
            <Issues title="ข้อผิดพลาด" issues={result.errors} total={result.error_count} kind="error" />
            <Issues title="คำเตือน" issues={result.warnings} total={result.warning_count} kind="warning" />
          </div>
        )}
      </main>

      <Toast toast={toast} />
      {confirming && (
        <Modal title="ยืนยันการนำเข้า" onClose={() => setConfirming(false)} width={520}>
          <div className="stack">
            <p>
              จะเพิ่มยาใหม่ {result.products_created.toLocaleString('th-TH')} รายการ, อัปเดต{' '}
              {result.products_updated.toLocaleString('th-TH')} รายการ
              {result.stock_lines > 0 &&
                `, และบวกยอดยกมาเข้าสต็อก ${result.stock_base_qty.toLocaleString('th-TH')} หน่วยเล็กสุด`}
            </p>
            <p className="muted small">การอัปเดตจะเขียนทับราคาเดิมของหน่วยขายที่ตรงกัน</p>
            <div className="modal-actions">
              <button type="button" className="btn" onClick={() => setConfirming(false)}>
                ยกเลิก
              </button>
              <button type="button" className="btn primary" autoFocus disabled={busy} onClick={() => send(true)}>
                {busy ? 'กำลังนำเข้า…' : 'นำเข้าจริง'}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
