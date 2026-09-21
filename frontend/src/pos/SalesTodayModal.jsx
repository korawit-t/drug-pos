import { useCallback, useEffect, useState } from 'react';
import { api } from '../api.js';
import { bahtOf, timeOf } from '../format.js';
import { labelsUrl, printPage, receiptUrl } from '../print.js';
import { Modal, PharmacistPicker, submitOnEnter, useLastPharmacist } from './ui.jsx';

function VoidForm({ sale, meta, onDone, onCancel }) {
  const [pharmacistId, setPharmacistId] = useLastPharmacist(meta.pharmacists);
  const [pin, setPin] = useState('');
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    if (!reason.trim()) return setError('ระบุเหตุผลที่ยกเลิก');
    if (!pharmacistId) return setError('เลือกเภสัชกรก่อน');
    if (!/^\d{4,6}$/.test(pin)) return setError('ใส่ PIN เป็นตัวเลข 4–6 หลัก');
    setBusy(true);
    setError('');
    try {
      await api(`/sales/${sale.id}/void`, { method: 'POST', body: { pharmacist_id: pharmacistId, pin, reason } });
      setPharmacistId(pharmacistId);
      onDone();
    } catch (err) {
      setError(err.message);
      setPin('');
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="void-form stack" onSubmit={submit}>
      <strong>ยกเลิกบิล {sale.number}</strong>
      <p className="muted small">สต็อกจะถูกคืนเข้า lot เดิม บิลยังอยู่ในระบบแต่ขึ้นว่ายกเลิก</p>
      <label className="field">
        เหตุผล
        <input autoFocus value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>
      <div className="field">
        เภสัชกรผู้อนุมัติ
        <PharmacistPicker pharmacists={meta.pharmacists} value={pharmacistId} onChange={setPharmacistId} />
      </div>
      <label className="field">
        PIN
        <input
          className="pin"
          type="password"
          inputMode="numeric"
          maxLength={6}
          autoComplete="off"
          value={pin}
          onKeyDown={submitOnEnter(submit)}
          onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))}
        />
      </label>
      {error && <p className="form-error">{error}</p>}
      <div className="modal-actions">
        <button type="button" className="btn" onClick={onCancel}>
          ไม่ยกเลิก
        </button>
        <button className="btn danger" disabled={busy}>
          {busy ? 'กำลังยกเลิก…' : 'ยืนยันยกเลิกบิล'}
        </button>
      </div>
    </form>
  );
}

export default function SalesTodayModal({ meta, onClose, onChanged }) {
  const [sales, setSales] = useState(null);
  const [voiding, setVoiding] = useState(null);
  const [error, setError] = useState('');

  const load = useCallback(() => {
    api('/sales')
      .then(setSales)
      .catch((err) => setError(err.message));
  }, []);
  useEffect(load, [load]);

  return (
    <Modal title="บิลวันนี้" onClose={onClose} width={760}>
      {error && <p className="form-error">{error}</p>}
      {voiding && (
        <VoidForm
          sale={voiding}
          meta={meta}
          onCancel={() => setVoiding(null)}
          onDone={() => {
            setVoiding(null);
            load();
            onChanged();
          }}
        />
      )}
      {sales === null && !error && <p className="muted">กำลังโหลด…</p>}
      {sales?.length === 0 && <p className="muted">วันนี้ยังไม่มีบิล</p>}
      {sales?.length > 0 && (
        <table className="sales-table">
          <thead>
            <tr>
              <th>เวลา</th>
              <th>เลขที่บิล</th>
              <th>ลูกค้า</th>
              <th className="col-num">ยอด</th>
              <th>ชำระ</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {sales.map((s) => (
              <tr key={s.id} className={s.status === 'voided' ? 'voided' : ''}>
                <td>{timeOf(s.created_at)}</td>
                <td>
                  {s.number}
                  {s.status === 'voided' && <span className="badge red small">ยกเลิก</span>}
                </td>
                <td>{s.buyer || <span className="muted">ทั่วไป</span>}</td>
                <td className="col-num">{bahtOf(s.total)}</td>
                <td>{s.payment_method === 'cash' ? 'เงินสด' : 'โอน'}</td>
                <td className="row-actions">
                  <button type="button" className="btn small" onClick={() => printPage(receiptUrl(s.id))}>
                    ใบเสร็จ
                  </button>
                  <button type="button" className="btn small" onClick={() => printPage(labelsUrl(s.id))}>
                    ฉลาก
                  </button>
                  {s.status === 'completed' && (
                    <button type="button" className="btn small danger" onClick={() => setVoiding(s)}>
                      ยกเลิกบิล
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Modal>
  );
}
