import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { api } from '../api.js';
import { baht, bahtOf, parseExpiry, thaiDate } from '../format.js';
import { Brand, TopLinks, ViewTabs } from '../nav.jsx';
import SearchBox from '../pos/SearchBox.jsx';
import { CategoryBadge, Modal, Toast, useToast } from '../pos/ui.jsx';
import {
  checkReceipt,
  draftProblems,
  lineTotalSatang,
  lineUnit,
  newReceipt,
  receiptPayload,
  receiptReducer,
  receiptTotalSatang,
} from './receipt.js';

function ReceiptRow({ line, index, readOnly, issues, showErrors, dispatch, onKeyDown }) {
  const unit = lineUnit(line);
  const expiry = parseExpiry(line.expiryText);
  const known = line.product.lots.find((lot) => lot.lot_no === line.lotNo.trim());
  const update = (changes) => dispatch({ type: 'update', key: line.key, changes });
  const qty = Number(line.qty) || 0;

  return (
    <tr onKeyDown={onKeyDown}>
      <td className="col-no">{index + 1}</td>
      <td>
        <div className="line-name">
          {line.product.display_name} <CategoryBadge product={line.product} />
        </div>
        {line.product.generic_name && <div className="muted small">{line.product.generic_name}</div>}
        {issues.warnings.map((w) => (
          <div key={w} className="line-warning">
            {w}
          </div>
        ))}
        {showErrors &&
          issues.errors.map((e) => (
            <div key={e} className="line-error">
              {e}
            </div>
          ))}
      </td>
      <td className="col-unit">
        <select value={line.unitId} disabled={readOnly} aria-label="หน่วย" onChange={(e) => update({ unitId: Number(e.target.value) })}>
          {line.product.units.map((u) => (
            <option key={u.id} value={u.id}>
              {u.name}
              {u.factor > 1 ? ` (${u.factor})` : ''}
            </option>
          ))}
        </select>
        {unit.factor > 1 && qty > 0 && (
          <div className="muted small">
            = {qty * unit.factor} {line.product.base_unit}
          </div>
        )}
      </td>
      <td className="col-qty">
        <input
          data-field="qty"
          inputMode="numeric"
          value={line.qty}
          disabled={readOnly}
          aria-label="จำนวน"
          onChange={(e) => update({ qty: e.target.value.replace(/\D/g, '') })}
        />
      </td>
      <td className="col-lot">
        <input
          value={line.lotNo}
          list={`lots-${line.key}`}
          disabled={readOnly}
          aria-label="เลขที่ lot"
          onChange={(e) => {
            const lotNo = e.target.value;
            const match = line.product.lots.find((lot) => lot.lot_no === lotNo.trim());
            // Picking a lot that's already in stock fills in its expiry.
            update(match && !line.expiryText ? { lotNo, expiryText: thaiDate(match.expiry_date) } : { lotNo });
          }}
        />
        <datalist id={`lots-${line.key}`}>
          {line.product.lots.map((lot) => (
            <option key={lot.lot_no} value={lot.lot_no}>
              หมดอายุ {thaiDate(lot.expiry_date, 'month')}
            </option>
          ))}
        </datalist>
        {known && (
          <div className="muted small">
            มีในสต็อก {known.qty} {line.product.base_unit}
          </div>
        )}
      </td>
      <td className="col-exp">
        <input
          value={line.expiryText}
          placeholder="03/2028"
          disabled={readOnly}
          aria-label="วันหมดอายุ"
          onChange={(e) => update({ expiryText: e.target.value })}
        />
        {expiry.iso && <div className="muted small">= {thaiDate(expiry.iso, 'long')}</div>}
        {expiry.error && <div className="line-error">อ่านไม่ออก</div>}
      </td>
      <td className="col-cost">
        <input
          inputMode="decimal"
          value={line.unitCost}
          disabled={readOnly}
          aria-label="ราคาทุนต่อหน่วย"
          onChange={(e) => update({ unitCost: e.target.value.replace(/[^\d.]/g, '') })}
        />
      </td>
      <td className="col-num strong">{baht(lineTotalSatang(line))}</td>
      <td className="col-del">
        {!readOnly && (
          <button
            type="button"
            className="icon-btn"
            aria-label={`ลบ ${line.product.display_name}`}
            onClick={() => dispatch({ type: 'remove', key: line.key })}
          >
            ×
          </button>
        )}
      </td>
    </tr>
  );
}

function RecentReceipts({ recent, currentId, onOpen }) {
  return (
    <section className="panel recent">
      <h3>ใบรับยาล่าสุด</h3>
      {recent === null && <p className="muted small">กำลังโหลด…</p>}
      {recent?.length === 0 && <p className="muted small">ยังไม่มีใบรับยา</p>}
      <ul className="pick-list">
        {recent?.map((p) => (
          <li
            key={p.id}
            className={p.id === currentId ? 'active' : ''}
            role="button"
            tabIndex={0}
            onClick={() => onOpen(p.id)}
            onKeyDown={(e) => e.key === 'Enter' && onOpen(p.id)}
          >
            <div>
              <strong>{p.is_opening_balance ? 'ยอดยกมา' : p.supplier_name || 'ยังไม่ระบุผู้ขาย'}</strong>
              <div className="muted small">
                {thaiDate(p.received_date)}
                {p.invoice_no && ` · ${p.invoice_no}`} · {p.item_count} รายการ · {bahtOf(p.total_cost)}
              </div>
            </div>
            <span className={`badge ${p.status === 'draft' ? 'amber' : 'green'}`}>
              {p.status === 'draft' ? 'ร่าง' : 'เข้าสต็อกแล้ว'}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function PostConfirm({ receipt, supplierName, totalSatang, busy, onCancel, onConfirm }) {
  return (
    <Modal title="บันทึกเข้าสต็อก" onClose={onCancel} width={640}>
      <div className="stack">
        <p>
          {receipt.isOpening ? 'ยอดยกมา' : `รับจาก ${supplierName}`}
          {receipt.invoiceNo && ` · ใบกำกับ ${receipt.invoiceNo}`} · {receipt.lines.length} รายการ · มูลค่า{' '}
          <strong>{baht(totalSatang)}</strong> บาท
        </p>
        <table className="sales-table">
          <thead>
            <tr>
              <th>รายการ</th>
              <th className="col-num">จำนวน</th>
              <th>lot</th>
              <th>หมดอายุ</th>
            </tr>
          </thead>
          <tbody>
            {receipt.lines.map((line) => (
              <tr key={line.key}>
                <td>{line.product.display_name}</td>
                <td className="col-num">
                  {line.qty} {lineUnit(line).name}
                </td>
                <td>{line.lotNo}</td>
                <td>{thaiDate(parseExpiry(line.expiryText).iso)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="alert warning">
          บันทึกแล้วแก้ไขหรือลบไม่ได้ ยาจะเข้าสต็อกทันที{!receipt.isOpening && ' และลงบัญชี ขย.9'}
        </div>
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onCancel}>
            กลับไปแก้
          </button>
          <button type="button" className="btn primary" autoFocus disabled={busy} onClick={onConfirm}>
            {busy ? 'กำลังบันทึก…' : 'ยืนยันบันทึกเข้าสต็อก'}
          </button>
        </div>
      </div>
    </Modal>
  );
}

export default function Receive({ meta, nav, active }) {
  const [receipt, dispatch] = useReducer(receiptReducer, meta.today, newReceipt);
  const [suppliers, setSuppliers] = useState([]);
  const [recent, setRecent] = useState(null);
  const [showErrors, setShowErrors] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toast, notify] = useToast();
  const searchRef = useRef(null);
  const tableRef = useRef(null);
  const readOnly = receipt.status === 'posted';

  const loadRecent = useCallback(() => {
    api('/purchases')
      .then(setRecent)
      .catch((err) => notify(err.message, 'error'));
  }, [notify]);

  useEffect(() => {
    api('/suppliers')
      .then(setSuppliers)
      .catch((err) => notify(err.message, 'error'));
  }, [notify]);

  useEffect(() => {
    if (!active) return;
    loadRecent();
    searchRef.current?.focus();
  }, [active, loadRecent]);

  // Closing or reloading the tab would lose what hasn't been saved.
  useEffect(() => {
    if (!receipt.dirty) return undefined;
    const warn = (e) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [receipt.dirty]);

  const check = useMemo(
    () => checkReceipt(receipt, { today: meta.today, nearExpiryDays: meta.near_expiry_days }),
    [receipt, meta],
  );
  const totalSatang = receiptTotalSatang(receipt);
  const supplierName = suppliers.find((s) => String(s.id) === receipt.supplierId)?.name || '';
  const set = (fields) => dispatch({ type: 'set', fields });

  async function addProduct(product, unitId) {
    dispatch({ type: 'add', product, unitId });
    try {
      const costs = await api('/purchases/last-costs', { params: { unit_ids: product.units.map((u) => u.id).join(',') } });
      dispatch({ type: 'lastCosts', productId: product.id, costs });
    } catch {
      // No earlier delivery to copy from — the cost stays for the user to type.
    }
  }

  const discardOk = () => !receipt.dirty || window.confirm('ทิ้งข้อมูลที่ยังไม่ได้บันทึก?');

  async function openReceipt(id) {
    if (id === receipt.id || !discardOk()) return;
    try {
      dispatch({ type: 'load', purchase: await api(`/purchases/${id}`) });
      setShowErrors(false);
    } catch (err) {
      notify(err.message, 'error');
    }
  }

  function startNew() {
    if (!discardOk()) return;
    dispatch({ type: 'reset', today: meta.today });
    setShowErrors(false);
    setTimeout(() => searchRef.current?.focus(), 0);
  }

  async function save(post) {
    setBusy(true);
    try {
      const saved = await api(receipt.id ? `/purchases/${receipt.id}` : '/purchases', {
        method: receipt.id ? 'PUT' : 'POST',
        body: receiptPayload(receipt, post),
      });
      dispatch({ type: 'load', purchase: saved });
      setShowErrors(false);
      setConfirming(false);
      notify(post ? `บันทึกเข้าสต็อกแล้ว ${saved.items.length} รายการ` : 'บันทึกร่างแล้ว');
      loadRecent();
    } catch (err) {
      setConfirming(false);
      notify(err.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  function saveDraft() {
    const problems = draftProblems(receipt);
    if (problems.length) {
      notify(problems[0], 'error');
      return;
    }
    save(false);
  }

  function askToPost() {
    if (!check.ok) {
      setShowErrors(true);
      notify(check.errors[0], 'error');
      return;
    }
    setConfirming(true);
  }

  async function deleteDraft() {
    if (!window.confirm('ลบร่างใบรับยานี้?')) return;
    try {
      await api(`/purchases/${receipt.id}`, { method: 'DELETE' });
      dispatch({ type: 'reset', today: meta.today });
      loadRecent();
      notify('ลบร่างแล้ว');
    } catch (err) {
      notify(err.message, 'error');
    }
  }

  // After scanning, Tab jumps into the newest line; Enter walks across a line and back to the scanner.
  function onEmptySearchKey(e) {
    if (e.key !== 'Tab' || e.shiftKey || !receipt.lines.length) return false;
    const rows = tableRef.current?.querySelectorAll('tbody tr');
    const qty = rows?.[rows.length - 1]?.querySelector('input[data-field="qty"]');
    qty?.focus();
    qty?.select();
    return true;
  }

  function onRowKeyDown(e) {
    if (e.key !== 'Enter' || e.nativeEvent.isComposing || e.target.tagName === 'BUTTON') return;
    e.preventDefault();
    const fields = [...e.currentTarget.querySelectorAll('input, select')];
    const next = fields[fields.indexOf(e.target) + 1];
    if (next) next.focus();
    else searchRef.current?.focus();
  }

  const title = readOnly ? 'ใบรับยา' : receipt.id ? 'แก้ไขร่างใบรับยา' : 'ใบรับยาใหม่';

  return (
    <div className="pos receive" hidden={!active}>
      <header className="topbar">
        <Brand name={meta.shop.name} />
        <ViewTabs nav={nav} />
        <TopLinks nav={nav} />
      </header>

      <main className="workspace">
        <section className="receive-main">
          <div className="panel">
            <div className="receipt-title">
              <h2>{title}</h2>
              {readOnly && (
                <span className="badge green">
                  เข้าสต็อกแล้ว · {receipt.postedBy}
                  {receipt.postedAt && ` · ${thaiDate(receipt.postedAt)}`}
                </span>
              )}
              {!readOnly && receipt.id && <span className="badge amber">ร่าง · {receipt.createdBy}</span>}
              {receipt.dirty && <span className="muted small">ยังไม่ได้บันทึก</span>}
            </div>
            <fieldset className="head-grid" disabled={readOnly}>
              <label className="check span-all">
                <input type="checkbox" checked={receipt.isOpening} onChange={(e) => set({ isOpening: e.target.checked })} />
                ยอดยกมา — นับยาที่มีอยู่แล้วตอนเริ่มใช้ระบบ (ไม่ลง ขย.9, รับของหมดอายุได้)
              </label>
              <label className="field">
                ผู้ขาย
                <select value={receipt.supplierId} onChange={(e) => set({ supplierId: e.target.value })}>
                  <option value="">{receipt.isOpening ? '— ไม่ระบุ —' : '— เลือกผู้ขาย —'}</option>
                  {suppliers.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                เลขที่ใบกำกับ / ใบส่งของ
                <input value={receipt.invoiceNo} onChange={(e) => set({ invoiceNo: e.target.value })} />
              </label>
              <label className="field">
                วันที่ในใบกำกับ
                <input type="date" max={meta.today} value={receipt.invoiceDate} onChange={(e) => set({ invoiceDate: e.target.value })} />
              </label>
              <label className="field">
                วันที่รับยา
                <input type="date" max={meta.today} value={receipt.receivedDate} onChange={(e) => set({ receivedDate: e.target.value })} />
              </label>
              <label className="field">
                หมายเหตุ
                <input value={receipt.note} onChange={(e) => set({ note: e.target.value })} />
              </label>
            </fieldset>
            {showErrors && check.errors.length > 0 && <div className="alert danger">{check.errors.join(' · ')}</div>}
          </div>

          {!readOnly && (
            <div className="receive-search">
              <SearchBox
                inputRef={searchRef}
                showPrice={false}
                placeholder="สแกนบาร์โค้ด หรือพิมพ์ชื่อยาเพื่อเพิ่มรายการ"
                onPick={addProduct}
                onEmptyKey={onEmptySearchKey}
                onNotFound={(q) => notify(`ไม่พบสินค้า "${q}" — เพิ่มสินค้าใหม่ได้ที่หลังร้าน`, 'error')}
              />
              <p className="muted small">
                สแกนแล้วกด <kbd>Tab</kbd> เพื่อกรอกรายการล่าสุด · <kbd>Enter</kbd> ไปช่องถัดไป จบแถวแล้วกลับมาสแกนต่อ ·
                วันหมดอายุพิมพ์ตามกล่องได้ เช่น 03/2028, 03/71, 31/03/2571
              </p>
            </div>
          )}

          <div className="cart-area">
            {receipt.lines.length === 0 ? (
              <div className="cart-empty">
                <p>ยังไม่มีรายการ</p>
                <p className="muted">สแกนบาร์โค้ดของยาที่รับเข้า หรือเลือกร่างจากรายการด้านขวา</p>
              </div>
            ) : (
              <table className="cart receive-table" ref={tableRef}>
                <thead>
                  <tr>
                    <th className="col-no">#</th>
                    <th>รายการ</th>
                    <th className="col-unit">หน่วย</th>
                    <th className="col-qty">จำนวน</th>
                    <th className="col-lot">เลขที่ lot</th>
                    <th className="col-exp">วันหมดอายุ</th>
                    <th className="col-cost">ทุน/หน่วย</th>
                    <th className="col-num">รวม</th>
                    <th className="col-del" aria-label="ลบ" />
                  </tr>
                </thead>
                <tbody>
                  {receipt.lines.map((line, i) => (
                    <ReceiptRow
                      key={line.key}
                      line={line}
                      index={i}
                      readOnly={readOnly}
                      issues={check.lines[line.key]}
                      showErrors={showErrors}
                      dispatch={dispatch}
                      onKeyDown={onRowKeyDown}
                    />
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="panel receive-foot">
            <span>
              {receipt.lines.length} รายการ · มูลค่ารวม <strong className="total">{baht(totalSatang)}</strong>
            </span>
            <span className="row-actions">
              {readOnly ? (
                <>
                  {!receipt.isOpening && (
                    <a className="btn" href={`/reports/ky9/?start=${receipt.receivedDate}&end=${receipt.receivedDate}`}>
                      ดูบัญชี ขย.9
                    </a>
                  )}
                  <button type="button" className="btn primary" onClick={startNew}>
                    เริ่มใบรับยาใหม่
                  </button>
                </>
              ) : (
                <>
                  {receipt.id && (
                    <button type="button" className="btn danger" onClick={deleteDraft}>
                      ลบร่าง
                    </button>
                  )}
                  <button type="button" className="btn" onClick={startNew}>
                    ใบใหม่
                  </button>
                  <button type="button" className="btn" onClick={saveDraft} disabled={busy}>
                    บันทึกร่าง
                  </button>
                  <button type="button" className="btn primary" onClick={askToPost} disabled={busy}>
                    บันทึกเข้าสต็อก
                  </button>
                </>
              )}
            </span>
          </div>
        </section>

        <aside className="side">
          <div className="side-scroll">
            <RecentReceipts recent={recent} currentId={receipt.id} onOpen={openReceipt} />
          </div>
        </aside>
      </main>

      <Toast toast={toast} />
      {confirming && (
        <PostConfirm
          receipt={receipt}
          supplierName={supplierName}
          totalSatang={totalSatang}
          busy={busy}
          onCancel={() => setConfirming(false)}
          onConfirm={() => save(true)}
        />
      )}
    </div>
  );
}
