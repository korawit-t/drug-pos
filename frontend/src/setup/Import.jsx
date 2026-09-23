import { useRef, useState } from 'react';
import { upload } from '../api.js';
import { Brand, TopLinks, ViewTabs } from '../nav.jsx';
import { Modal, Toast, useToast } from '../pos/ui.jsx';

function Summary({ result }) {
  const cards = [
    ['ยาใหม่', result.products_created],
    ['ยาที่อัปเดต', result.products_updated],
    ['หน่วยขายใหม่', result.units_created],
    ['หน่วยขายที่อัปเดต', result.units_updated],
    ['รายการยอดยกมา', result.stock_lines],
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
  const [file, setFile] = useState(null);
  const [withStock, setWithStock] = useState(false);
  const [result, setResult] = useState(null);
  const [checkedKey, setCheckedKey] = useState('');
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toast, notify] = useToast();
  const inputRef = useRef(null);

  const key = file ? `${file.name}|${file.size}|${file.lastModified}|${withStock}` : '';
  const checked = key !== '' && checkedKey === key && result;
  const readyToImport = checked && !result.error_count && !result.committed;

  function pickFile(nextFile) {
    setFile(nextFile);
    setResult(null);
    setCheckedKey('');
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
    setBusy(true);
    setConfirming(false);
    try {
      const data = await upload('/import/products', body);
      setResult(data);
      setCheckedKey(key);
      if (data.committed) {
        notify(`นำเข้าแล้ว ${data.rows.toLocaleString('th-TH')} แถว`);
        if (inputRef.current) inputRef.current.value = '';
        setFile(null);
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
        <div className="panel">
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
            นำเข้าซ้ำได้ ระบบจับคู่ด้วยบาร์โค้ด หรือชื่อการค้า + ความแรง แล้วอัปเดตให้ จึงใช้ปรับราคาทั้งร้านได้ด้วย
          </p>
        </div>

        <div className="panel">
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
          {withStock && (
            <div className="alert warning">
              ยอดยกมาจะถูก <strong>บวกเพิ่ม</strong> เข้าสต็อกทุกครั้งที่นำเข้า ถ้านำเข้าไฟล์เดิมซ้ำ สต็อกจะเกิน —
              ใช้ตอนเริ่มใช้ระบบครั้งแรกครั้งเดียว
            </div>
          )}
          <div className="row-actions">
            <button type="button" className="btn" disabled={busy || !file} onClick={() => send(false)}>
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

        {result && (
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
