import { useState } from 'react';
import { api } from '../api.js';
import { thaiDate, toGregorianDate } from '../format.js';
import { baseQty, billNeeds, lineUnit } from './bill.js';
import { Modal, PharmacistPicker, submitOnEnter, useLastPharmacist } from './ui.jsx';

// One PIN per bill: the pharmacist reviews every line that needs them, can
// fix the label text, and confirms them all at once.
export default function PharmacistModal({ bill, plan, meta, dispatch, onClose, onApproved }) {
  const { pending, needsBuyer, needsRx } = billNeeds(bill);
  const [pharmacistId, setPharmacistId] = useLastPharmacist(meta.pharmacists);
  const [dosages, setDosages] = useState(() => Object.fromEntries(pending.map((l) => [l.key, l.dosage])));
  const [buyerName, setBuyerName] = useState(bill.buyerName || bill.customer?.name || '');
  const [rx, setRx] = useState(bill.rx);
  const [pin, setPin] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    if (!pharmacistId) return setError('เลือกเภสัชกรก่อน');
    if (needsBuyer && !buyerName.trim()) return setError('กรอกชื่อผู้ซื้อ (มียาที่ต้องลงบัญชี ขย.11)');
    if (needsRx && (!rx.prescriber.trim() || !rx.facility.trim())) {
      return setError('กรอกชื่อผู้สั่งจ่ายและสถานพยาบาลจากใบสั่งยา');
    }
    if (!/^\d{4,6}$/.test(pin)) return setError('ใส่ PIN เป็นตัวเลข 4–6 หลัก');

    setBusy(true);
    setError('');
    try {
      const result = await api('/approvals/dispense', {
        method: 'POST',
        body: {
          pharmacist_id: pharmacistId,
          pin,
          client_uuid: bill.clientUuid,
          lines: pending.map((l) => ({ key: l.key, unit_id: l.unitId, qty: l.qty, dosage_text: dosages[l.key] })),
        },
      });
      for (const line of pending) {
        if (dosages[line.key] !== line.dosage) {
          dispatch({ type: 'update', key: line.key, changes: { dosage: dosages[line.key] } });
        }
      }
      dispatch({ type: 'setFields', fields: { buyerName: needsBuyer ? buyerName.trim() : bill.buyerName, rx } });
      dispatch({ type: 'approve', tokens: result.tokens, pharmacistName: result.pharmacist_name });
      setPharmacistId(pharmacistId);
      onApproved();
    } catch (err) {
      setError(err.message);
      setPin('');
    } finally {
      setBusy(false);
    }
  }

  function hold() {
    onClose('hold');
  }

  return (
    <Modal title="เภสัชกรยืนยันการจ่ายยา" onClose={() => onClose()} width={640}>
      <form onSubmit={submit} className="stack">
        <p className="muted small">{pending.length} รายการต้องให้เภสัชกรยืนยันก่อนรับเงิน</p>
        {pending.map((line) => {
          const first = plan[line.key]?.allocations[0];
          return (
            <div key={line.key} className="approve-line">
              <div className="line-name">
                {line.product.display_name} · {line.qty} {lineUnit(line).name}
                <span className="muted"> ({baseQty(line)} {line.product.base_unit})</span>
              </div>
              {first && (
                <div className="muted small">
                  lot {first.lot_no} · หมดอายุ {thaiDate(first.expiry_date, 'month')}
                </div>
              )}
              <label className="field">
                วิธีใช้ (พิมพ์ลงฉลาก)
                <input
                  value={dosages[line.key]}
                  onChange={(e) => setDosages({ ...dosages, [line.key]: e.target.value })}
                />
              </label>
            </div>
          );
        })}

        {needsBuyer && (
          <label className="field">
            ชื่อผู้ซื้อ (ลงบัญชี ขย.11)
            <input value={buyerName} onChange={(e) => setBuyerName(e.target.value)} />
          </label>
        )}

        {needsRx && (
          <fieldset className="rx">
            <legend>ข้อมูลใบสั่งยา</legend>
            <label className="field">
              ผู้สั่งจ่าย
              <input value={rx.prescriber} onChange={(e) => setRx({ ...rx, prescriber: e.target.value })} />
            </label>
            <label className="field">
              เลขที่ใบอนุญาต
              <input value={rx.license} onChange={(e) => setRx({ ...rx, license: e.target.value })} />
            </label>
            <label className="field">
              สถานพยาบาล
              <input value={rx.facility} onChange={(e) => setRx({ ...rx, facility: e.target.value })} />
            </label>
            <label className="field">
              วันที่ในใบสั่งยา
              <input
                type="date"
                value={rx.date}
                max={meta.today}
                onChange={(e) => setRx({ ...rx, date: toGregorianDate(e.target.value) })}
              />
            </label>
          </fieldset>
        )}

        <div className="field">
          เภสัชกร
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
          <button type="button" className="btn" onClick={() => onClose()}>
            ยกเลิก <kbd>Esc</kbd>
          </button>
          <button type="button" className="btn" onClick={hold}>
            พักบิลรอเภสัชกร
          </button>
          <button className="btn primary" disabled={busy}>
            {busy ? 'กำลังตรวจสอบ…' : 'ยืนยัน'} <kbd>Enter</kbd>
          </button>
        </div>
      </form>
    </Modal>
  );
}
