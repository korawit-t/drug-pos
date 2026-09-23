import { useEffect, useState } from 'react';
import { api } from '../api.js';
import { thaiDate, toGregorianDate } from '../format.js';
import { baseQty, billNeeds, lineAlerts, lineUnit } from './bill.js';
import { AllergyList, Modal, PharmacistPicker, submitOnEnter, useLastPharmacist } from './ui.jsx';

function CustomerAllergies({ customer }) {
  if (!customer) {
    return <div className="alert info">ลูกค้าทั่วไป — ไม่มีประวัติแพ้ยาในระบบ ถามลูกค้าก่อนจ่ายยา</div>;
  }
  if (!customer.allergies.length) {
    return <div className="alert info">{customer.name}: ไม่มีประวัติแพ้ยาในระบบ — ถามลูกค้าอีกครั้งก่อนจ่ายยา</div>;
  }
  return (
    <div className="alert danger">
      <strong>ประวัติแพ้ยาของ {customer.name}</strong>
      <AllergyList allergies={customer.allergies} />
    </div>
  );
}

// One PIN per bill: the pharmacist reviews every line that needs them, can fix
// the label text, decides on any allergy alert, and confirms them all at once.
export default function PharmacistModal({ bill, plan, meta, alerts, dispatch, onClose, onApproved }) {
  const { pending, needsBuyer, needsRx } = billNeeds(bill, alerts);
  const [pharmacistId, setPharmacistId] = useLastPharmacist(meta.pharmacists);
  const [dosages, setDosages] = useState(() => Object.fromEntries(pending.map((l) => [l.key, l.dosage])));
  const [notes, setNotes] = useState(() => Object.fromEntries(pending.map((l) => [l.key, l.allergyNote || ''])));
  const [buyerName, setBuyerName] = useState(bill.buyerName || bill.customer?.name || '');
  const [rx, setRx] = useState(bill.rx);
  const [pin, setPin] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const alerted = pending.filter((l) => lineAlerts(l, alerts).length > 0);

  // Every line was taken off the bill here — nothing left to confirm.
  useEffect(() => {
    if (pending.length === 0) onClose();
  }, [pending.length, onClose]);

  async function submit(e) {
    e.preventDefault();
    if (!pharmacistId) return setError('เลือกเภสัชกรก่อน');
    const missing = alerted.find((l) => !notes[l.key]?.trim());
    if (missing) return setError(`ระบุเหตุผลที่ยังจ่าย ${missing.product.display_name} หรือเอาออกจากบิล`);
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
          customer_id: bill.customer?.id ?? null,
          lines: pending.map((l) => ({
            key: l.key,
            unit_id: l.unitId,
            qty: l.qty,
            dosage_text: dosages[l.key],
            allergy_note: notes[l.key] || '',
          })),
        },
      });
      for (const line of pending) {
        if (dosages[line.key] !== line.dosage) {
          dispatch({ type: 'update', key: line.key, changes: { dosage: dosages[line.key] } });
        }
      }
      dispatch({ type: 'setFields', fields: { buyerName: needsBuyer ? buyerName.trim() : bill.buyerName, rx } });
      dispatch({
        type: 'approve',
        tokens: result.tokens,
        pharmacistName: result.pharmacist_name,
        allergyKeys: result.allergy_keys,
        notes: Object.fromEntries(Object.entries(notes).map(([key, note]) => [key, note.trim()])),
        customerId: bill.customer?.id ?? null,
      });
      setPharmacistId(pharmacistId);
      onApproved();
    } catch (err) {
      setError(err.message);
      setPin('');
    } finally {
      setBusy(false);
    }
  }

  if (pending.length === 0) return null;

  return (
    <Modal title="เภสัชกรยืนยันการจ่ายยา" onClose={() => onClose()} width={660}>
      <form onSubmit={submit} className="stack">
        <CustomerAllergies customer={bill.customer} />
        <p className="muted small">{pending.length} รายการต้องให้เภสัชกรยืนยันก่อนรับเงิน</p>
        {pending.map((line) => {
          const first = plan[line.key]?.allocations[0];
          const found = lineAlerts(line, alerts);
          return (
            <div key={line.key} className={`approve-line ${found.length ? 'has-alert' : ''}`}>
              <div className="line-name">
                {line.product.display_name} · {line.qty} {lineUnit(line).name}
                <span className="muted"> ({baseQty(line)} {line.product.base_unit})</span>
              </div>
              {first && (
                <div className="muted small">
                  lot {first.lot_no} · หมดอายุ {thaiDate(first.expiry_date, 'month')}
                </div>
              )}
              {found.map((alert) => (
                <div key={alert.allergy_id} className={`line-alert ${alert.level}`}>
                  <strong>{alert.level === 'direct' ? 'แพ้ยา' : 'อาจแพ้ข้ามกลุ่ม'}</strong> {alert.message}
                  {alert.reaction && ` · อาการเดิม: ${alert.reaction}`} · {alert.severity_label}
                </div>
              ))}
              {found.length > 0 && (
                <div className="allergy-decision">
                  <label className="field">
                    เหตุผลที่ยังจ่าย (บันทึกไว้กับบิลนี้)
                    <input
                      autoFocus={line.key === alerted[0]?.key}
                      value={notes[line.key]}
                      placeholder="ลูกค้ายืนยันว่าเคยใช้แล้วไม่แพ้"
                      onChange={(e) => {
                        setNotes({ ...notes, [line.key]: e.target.value });
                        setError('');
                      }}
                    />
                  </label>
                  <button
                    type="button"
                    className="btn small danger"
                    onClick={() => dispatch({ type: 'remove', key: line.key })}
                  >
                    ไม่จ่าย — เอาออกจากบิล
                  </button>
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
            autoFocus={alerted.length === 0}
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
          <button type="button" className="btn" onClick={() => onClose('hold')}>
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
