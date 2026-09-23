import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { api } from '../api.js';
import { thaiDate } from '../format.js';
import { Brand, TopLinks, ViewTabs } from '../nav.jsx';
import SearchBox from '../pos/SearchBox.jsx';
import { Modal, PharmacistPicker, submitOnEnter, Toast, useLastPharmacist, useToast } from '../pos/ui.jsx';
import {
  checkSheet,
  countedQty,
  difference,
  draftProblems,
  isCounted,
  newSheet,
  sheetPayload,
  sheetReducer,
  sheetSummary,
} from './sheet.js';

const signed = (n) => (n > 0 ? `+${n}` : String(n));

function LotCell({ line, issues, showErrors }) {
  const { lot } = line;
  return (
    <>
      <div className="line-name">
        {lot.product_name}
        {lot.expired && <span className="badge red small">หมดอายุ</span>}
      </div>
      <div className="muted small">
        lot {lot.lot_no} · หมดอายุ {thaiDate(lot.expiry_date, 'month')}
        {lot.storage_location && ` · ${lot.storage_location}`}
      </div>
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
    </>
  );
}

function CountRow({ line, index, readOnly, reasons, issues, showErrors, dispatch, onKeyDown }) {
  const { lot } = line;
  const counted = countedQty(line);
  const diff = difference(line);
  const update = (changes) => dispatch({ type: 'update', key: line.key, changes });
  const units = [{ name: lot.base_unit, factor: 1 }, ...lot.units];
  const diffText = line.diffText !== null ? line.diffText : diff === null ? '' : signed(diff);

  return (
    <tr onKeyDown={onKeyDown} className={diff ? 'has-difference' : ''}>
      <td className="col-no">{index + 1}</td>
      <td>
        <LotCell line={line} issues={issues} showErrors={showErrors} />
      </td>
      <td className="col-num">
        {line.systemQty} <span className="muted">{lot.base_unit}</span>
      </td>
      <td className="col-count">
        <div className="count-fields">
          <input
            data-field="counted"
            inputMode="numeric"
            value={line.qtyText}
            disabled={readOnly}
            aria-label={`นับได้ ${lot.product_name} lot ${lot.lot_no}`}
            onChange={(e) => update({ qtyText: e.target.value.replace(/[^\d]/g, '') })}
          />
          {units.length > 1 && (
            <select
              value={line.factor}
              disabled={readOnly}
              aria-label="หน่วยที่นับ"
              onChange={(e) => update({ factor: Number(e.target.value), looseText: '' })}
            >
              {units.map((u) => (
                <option key={u.factor} value={u.factor}>
                  {u.name}
                  {u.factor > 1 ? ` (${u.factor})` : ''}
                </option>
              ))}
            </select>
          )}
        </div>
        {line.factor > 1 && (
          <div className="count-fields loose">
            <span className="muted small">+ เศษ</span>
            <input
              inputMode="numeric"
              value={line.looseText}
              disabled={readOnly}
              aria-label="เศษที่เหลือ"
              onChange={(e) => update({ looseText: e.target.value.replace(/[^\d]/g, '') })}
            />
            <span className="muted small">{lot.base_unit}</span>
          </div>
        )}
        {line.factor > 1 && Number.isInteger(counted) && (
          <div className="muted small">
            = {counted} {lot.base_unit}
          </div>
        )}
      </td>
      <td className="col-diff">
        <input
          className={diff ? (diff < 0 ? 'shortage' : 'surplus') : ''}
          value={diffText}
          disabled={readOnly}
          placeholder="0"
          aria-label={`ส่วนต่าง ${lot.product_name} lot ${lot.lot_no}`}
          onChange={(e) => dispatch({ type: 'difference', key: line.key, text: e.target.value.replace(/[^\d+-]/g, '') })}
        />
      </td>
      <td className="col-reason">
        <select
          value={line.reason}
          disabled={readOnly}
          aria-label="สาเหตุ"
          onChange={(e) => update({ reason: e.target.value })}
        >
          <option value="">— เลือก —</option>
          {reasons.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>
        <input
          value={line.note}
          disabled={readOnly}
          placeholder="หมายเหตุ"
          aria-label="หมายเหตุ"
          onChange={(e) => update({ note: e.target.value })}
        />
      </td>
      <td className="col-del">
        {!readOnly && (
          <button
            type="button"
            className="icon-btn"
            aria-label={`เอา ${lot.product_name} lot ${lot.lot_no} ออก`}
            onClick={() => dispatch({ type: 'remove', key: line.key })}
          >
            ×
          </button>
        )}
      </td>
    </tr>
  );
}

function RecentCounts({ recent, currentId, onOpen }) {
  return (
    <section className="panel recent">
      <h3>ใบนับสต็อกล่าสุด</h3>
      {recent === null && <p className="muted small">กำลังโหลด…</p>}
      {recent?.length === 0 && <p className="muted small">ยังไม่เคยนับสต็อก</p>}
      <ul className="pick-list">
        {recent?.map((c) => (
          <li
            key={c.id}
            className={c.id === currentId ? 'active' : ''}
            role="button"
            tabIndex={0}
            onClick={() => onOpen(c.id)}
            onKeyDown={(e) => e.key === 'Enter' && onOpen(c.id)}
          >
            <div>
              <strong>{thaiDate(c.counted_date)}</strong>
              <div className="muted small">
                {c.item_count} lot · ยอดไม่ตรง {c.diff_count}
                {c.note && ` · ${c.note}`}
              </div>
            </div>
            <span className={`badge ${c.status === 'draft' ? 'amber' : 'green'}`}>
              {c.status === 'draft' ? 'ร่าง' : 'ปรับยอดแล้ว'}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function AdjustConfirm({ sheet, meta, summary, busy, onCancel, onConfirm }) {
  const [pharmacistId, setPharmacistId] = useLastPharmacist(meta.pharmacists);
  const [pin, setPin] = useState('');
  const [error, setError] = useState('');
  const changed = sheet.lines.filter((line) => isCounted(line) && difference(line) !== 0);
  const reasonLabel = (value) => meta.adjust_reasons.find((r) => r.value === value)?.label || '';

  function submit(e) {
    e.preventDefault();
    if (!pharmacistId) return setError('เลือกเภสัชกรก่อน');
    if (!/^\d{4,6}$/.test(pin)) return setError('ใส่ PIN เป็นตัวเลข 4–6 หลัก');
    setError('');
    onConfirm({ pharmacistId, pin });
  }

  return (
    <Modal title="ปรับยอดสต็อกตามที่นับได้" onClose={onCancel} width={720}>
      <form onSubmit={submit} className="stack">
        <p>
          นับ {summary.lines} lot · ยอดตรง {summary.counted - summary.differing} · <strong>ยอดไม่ตรง {summary.differing}</strong>
        </p>
        {changed.length === 0 ? (
          <div className="alert success">นับแล้วยอดตรงทุกรายการ — บันทึกไว้เป็นหลักฐานการนับได้เลย</div>
        ) : (
          <table className="sales-table">
            <thead>
              <tr>
                <th>รายการ</th>
                <th className="col-num">ระบบมี</th>
                <th className="col-num">นับได้</th>
                <th className="col-num">ต่าง</th>
                <th>สาเหตุ</th>
              </tr>
            </thead>
            <tbody>
              {changed.map((line) => (
                <tr key={line.key}>
                  <td>
                    {line.lot.product_name}
                    <div className="muted small">lot {line.lot.lot_no}</div>
                  </td>
                  <td className="col-num">{line.systemQty}</td>
                  <td className="col-num">{countedQty(line)}</td>
                  <td className={`col-num ${difference(line) < 0 ? 'text-danger' : ''}`}>
                    <strong>{signed(difference(line))}</strong>
                  </td>
                  <td>
                    {reasonLabel(line.reason)}
                    {line.note && <div className="muted small">{line.note}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="alert warning">
          ปรับแล้วแก้ไม่ได้ ยอดคงเหลือจะเปลี่ยนทันทีและบันทึกชื่อเภสัชกรผู้อนุมัติไว้ทุกรายการ
        </div>
        <div className="field">
          เภสัชกรผู้อนุมัติ
          <PharmacistPicker pharmacists={meta.pharmacists} value={pharmacistId} onChange={setPharmacistId} />
        </div>
        <label className="field">
          PIN เภสัชกร
          <input
            className="pin"
            type="password"
            inputMode="numeric"
            maxLength={6}
            autoFocus
            autoComplete="off"
            value={pin}
            onKeyDown={submitOnEnter(submit)}
            onChange={(e) => {
              setPin(e.target.value.replace(/\D/g, ''));
              setError('');
            }}
          />
        </label>
        {error && <p className="form-error">{error}</p>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onCancel}>
            กลับไปแก้
          </button>
          <button className="btn primary" disabled={busy}>
            {busy ? 'กำลังปรับยอด…' : 'ยืนยันปรับยอด'} <kbd>Enter</kbd>
          </button>
        </div>
      </form>
    </Modal>
  );
}

export default function Count({ meta, nav, active }) {
  const [sheet, dispatch] = useReducer(sheetReducer, meta.today, newSheet);
  const [recent, setRecent] = useState(null);
  const [showErrors, setShowErrors] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toast, notify] = useToast();
  const searchRef = useRef(null);
  const tableRef = useRef(null);
  const readOnly = sheet.status === 'posted';

  const loadRecent = useCallback(() => {
    api('/stock-counts')
      .then(setRecent)
      .catch((err) => notify(err.message, 'error'));
  }, [notify]);

  useEffect(() => {
    if (!active) return;
    loadRecent();
    searchRef.current?.focus();
  }, [active, loadRecent]);

  // Closing or reloading the tab would lose a count that hasn't been saved.
  useEffect(() => {
    if (!sheet.dirty) return undefined;
    const warn = (e) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [sheet.dirty]);

  const check = useMemo(() => checkSheet(sheet, { today: meta.today }), [sheet, meta.today]);
  const summary = sheetSummary(sheet);
  const set = (fields) => dispatch({ type: 'set', fields });

  async function addProduct(product) {
    try {
      const lots = await api('/stock/lots', { params: { product_id: product.id } });
      if (!lots.length) {
        notify(`${product.display_name}: ไม่มีของในระบบ — ของที่ระบบไม่รู้จักให้รับเข้าเป็นยอดยกมาที่หน้ารับยาเข้า`, 'error');
        return;
      }
      dispatch({ type: 'add', lots });
    } catch (err) {
      notify(err.message, 'error');
    }
  }

  async function addExpired() {
    try {
      const lots = await api('/stock/lots/expired');
      if (!lots.length) {
        notify('ไม่มียาหมดอายุค้างอยู่บนชั้น');
        return;
      }
      dispatch({ type: 'add', lots, prefill: { qtyText: '0', reason: 'expired' } });
      notify(`เพิ่มยาหมดอายุ ${lots.length} lot (ใส่นับได้ = 0 ไว้ให้ ตรวจก่อนปรับยอด)`);
    } catch (err) {
      notify(err.message, 'error');
    }
  }

  async function refreshStock() {
    if (!sheet.lines.length) return;
    try {
      const lots = await api('/stock/lots', { params: { ids: sheet.lines.map((l) => l.lot.id).join(',') } });
      const before = new Map(sheet.lines.map((l) => [l.lot.id, l.systemQty]));
      dispatch({ type: 'refresh', lots });
      const moved = lots.filter((lot) => before.get(lot.id) !== lot.qty).length;
      notify(moved ? `ยอดในระบบเปลี่ยนไป ${moved} รายการ — ตรวจรายการที่มีเครื่องหมายเตือน` : 'ยอดในระบบยังตรงกับตอนนับ');
    } catch (err) {
      notify(err.message, 'error');
    }
  }

  const discardOk = () => !sheet.dirty || window.confirm('ทิ้งข้อมูลที่ยังไม่ได้บันทึก?');

  async function openSheet(id) {
    if (id === sheet.id || !discardOk()) return;
    try {
      dispatch({ type: 'load', count: await api(`/stock-counts/${id}`) });
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

  async function save(post, approval) {
    setBusy(true);
    try {
      const saved = await api(sheet.id ? `/stock-counts/${sheet.id}` : '/stock-counts', {
        method: sheet.id ? 'PUT' : 'POST',
        body: sheetPayload(sheet, post, approval),
      });
      dispatch({ type: 'load', count: saved });
      setShowErrors(false);
      setConfirming(false);
      notify(post ? `ปรับยอดแล้ว ${summary.differing} รายการ` : 'บันทึกร่างแล้ว');
      loadRecent();
    } catch (err) {
      // Back to the sheet with the PIN box cleared — whatever went wrong is fixed there.
      setConfirming(false);
      notify(err.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  function saveDraft() {
    const problems = draftProblems(sheet);
    if (problems.length) {
      notify(problems[0], 'error');
      return;
    }
    save(false);
  }

  function askToAdjust() {
    if (!check.ok) {
      setShowErrors(true);
      notify(check.errors[0], 'error');
      return;
    }
    setConfirming(true);
  }

  async function deleteDraft() {
    if (!window.confirm('ลบร่างใบนับสต็อกนี้?')) return;
    try {
      await api(`/stock-counts/${sheet.id}`, { method: 'DELETE' });
      dispatch({ type: 'reset', today: meta.today });
      loadRecent();
      notify('ลบร่างแล้ว');
    } catch (err) {
      notify(err.message, 'error');
    }
  }

  // After picking a drug, Tab jumps into the newest line; Enter walks along the row.
  function onEmptySearchKey(e) {
    if (e.key !== 'Tab' || e.shiftKey || !sheet.lines.length) return false;
    const rows = tableRef.current?.querySelectorAll('tbody tr');
    const input = rows?.[rows.length - 1]?.querySelector('input[data-field="counted"]');
    input?.focus();
    input?.select();
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

  const title = readOnly ? 'ใบนับสต็อก' : sheet.id ? 'แก้ไขร่างใบนับสต็อก' : 'นับสต็อกใหม่';

  return (
    <div className="pos receive count" hidden={!active}>
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
                  ปรับยอดแล้ว · อนุมัติโดย {sheet.approvedBy}
                  {sheet.postedAt && ` · ${thaiDate(sheet.postedAt)}`}
                </span>
              )}
              {!readOnly && sheet.id && <span className="badge amber">ร่าง · {sheet.createdBy}</span>}
              {sheet.dirty && <span className="muted small">ยังไม่ได้บันทึก</span>}
            </div>
            <fieldset className="head-grid" disabled={readOnly}>
              <label className="field">
                วันที่นับ
                <input type="date" max={meta.today} value={sheet.countedDate} onChange={(e) => set({ countedDate: e.target.value })} />
              </label>
              <label className="field">
                หมายเหตุ (เช่น นับรอบเดือน ก.ย.)
                <input value={sheet.note} onChange={(e) => set({ note: e.target.value })} />
              </label>
            </fieldset>
            {showErrors && check.errors.length > 0 && <div className="alert danger">{check.errors.join(' · ')}</div>}
          </div>

          {!readOnly && (
            <div className="receive-search">
              <SearchBox
                inputRef={searchRef}
                showPrice={false}
                placeholder="สแกนบาร์โค้ด หรือพิมพ์ชื่อยาที่จะนับ (ขึ้นทุก lot ของยานั้น)"
                onPick={addProduct}
                onEmptyKey={onEmptySearchKey}
                onNotFound={(q) => notify(`ไม่พบสินค้า "${q}"`, 'error')}
              />
              <div className="count-actions">
                <button type="button" className="btn small" onClick={addExpired}>
                  เพิ่มยาหมดอายุทั้งหมด
                </button>
                <button type="button" className="btn small" onClick={refreshStock} disabled={!sheet.lines.length}>
                  ดึงยอดล่าสุด
                </button>
                <span className="muted small">
                  นับเป็นกล่อง/แผงได้ · ของแตกหรือหายพิมพ์ในช่อง “ต่าง” เช่น <kbd>-5</kbd> · <kbd>Enter</kbd> ไปช่องถัดไป
                </span>
              </div>
            </div>
          )}

          <div className="cart-area">
            {sheet.lines.length === 0 ? (
              <div className="cart-empty">
                <p>ยังไม่มีรายการ</p>
                <p className="muted">
                  สแกนหรือพิมพ์ชื่อยาที่จะนับ — ระบบจะดึงทุก lot ของยานั้นมาให้นับทีละ lot
                  <br />
                  ยาที่ระบบยังไม่รู้จักหรือ lot ที่หมดไปแล้ว ให้รับเข้าเป็น “ยอดยกมา” ที่หน้ารับยาเข้า
                </p>
              </div>
            ) : (
              <table className="cart receive-table count-table" ref={tableRef}>
                <thead>
                  <tr>
                    <th className="col-no">#</th>
                    <th>รายการ / lot</th>
                    <th className="col-num">ระบบมี</th>
                    <th className="col-count">นับได้</th>
                    <th className="col-diff">ต่าง</th>
                    <th className="col-reason">สาเหตุที่ยอดไม่ตรง</th>
                    <th className="col-del" aria-label="ลบ" />
                  </tr>
                </thead>
                <tbody>
                  {sheet.lines.map((line, i) => (
                    <CountRow
                      key={line.key}
                      line={line}
                      index={i}
                      readOnly={readOnly}
                      reasons={meta.adjust_reasons}
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
              นับแล้ว {summary.counted}/{summary.lines} lot
              {summary.uncounted > 0 && <span className="text-danger"> · ยังไม่ได้นับ {summary.uncounted}</span>}
              {summary.shortage > 0 && <span className="text-danger"> · ขาด {summary.shortage}</span>}
              {summary.surplus > 0 && <span className="surplus-text"> · เกิน {summary.surplus}</span>}
            </span>
            <span className="row-actions">
              {readOnly ? (
                <>
                  <a className="btn" href="/reports/adjustments/">
                    ดูประวัติการปรับยอด
                  </a>
                  <button type="button" className="btn primary" onClick={startNew}>
                    นับใบใหม่
                  </button>
                </>
              ) : (
                <>
                  {sheet.id && (
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
                  <button type="button" className="btn primary" onClick={askToAdjust} disabled={busy}>
                    ปรับยอดตามที่นับ
                  </button>
                </>
              )}
            </span>
          </div>
        </section>

        <aside className="side">
          <div className="side-scroll">
            <RecentCounts recent={recent} currentId={sheet.id} onOpen={openSheet} />
          </div>
        </aside>
      </main>

      <Toast toast={toast} />
      {confirming && (
        <AdjustConfirm
          sheet={sheet}
          meta={meta}
          summary={summary}
          busy={busy}
          onCancel={() => setConfirming(false)}
          onConfirm={(approval) => save(true, approval)}
        />
      )}
    </div>
  );
}
