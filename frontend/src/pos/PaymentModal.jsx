import { QRCodeSVG } from 'qrcode.react';
import { useEffect, useState } from 'react';
import { api } from '../api.js';
import { baht, toSatang } from '../format.js';
import { checkoutPayload } from './bill.js';
import { Modal, submitOnEnter } from './ui.jsx';

function quickAmounts(total) {
  const steps = [20, 50, 100, 500, 1000];
  const amounts = steps.map((s) => Math.ceil(total / (s * 100)) * s * 100).filter((a) => a > total);
  return [...new Set(amounts)].slice(0, 4);
}

export default function PaymentModal({ bill, totalSatang, promptpayEnabled, onClose, onPaid, onApprovalExpired }) {
  const [method, setMethod] = useState('cash');
  const [cash, setCash] = useState('');
  const [qr, setQr] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const cashSatang = cash === '' ? 0 : toSatang(cash);
  const change = cashSatang - totalSatang;

  useEffect(() => {
    if (method !== 'transfer' || qr || !promptpayEnabled) return;
    api('/promptpay', { params: { amount: (totalSatang / 100).toFixed(2) } })
      .then(setQr)
      .catch((err) => setQr({ error: err.message }));
  }, [method, qr, promptpayEnabled, totalSatang]);

  async function pay(received = cashSatang) {
    if (busy) return;
    if (method === 'cash' && received < totalSatang) {
      setError('รับเงินไม่พอ');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const sale = await api('/sales', {
        method: 'POST',
        body: checkoutPayload(bill, {
          method,
          cashReceived: method === 'cash' ? (received / 100).toFixed(2) : null,
        }),
      });
      onPaid(sale);
    } catch (err) {
      if (err.status === 409) onApprovalExpired(err.message);
      else setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="ชำระเงิน" onClose={onClose} width={520}>
      <div className="pay-total">
        <span className="muted">ยอดที่ต้องชำระ</span>
        <span className="total">{baht(totalSatang)}</span>
      </div>
      <div className="segmented" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={method === 'cash'}
          className={method === 'cash' ? 'active' : ''}
          onClick={() => setMethod('cash')}
        >
          เงินสด
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={method === 'transfer'}
          className={method === 'transfer' ? 'active' : ''}
          onClick={() => setMethod('transfer')}
        >
          โอน / QR พร้อมเพย์
        </button>
      </div>

      {method === 'cash' ? (
        <form
          className="stack"
          onSubmit={(e) => {
            e.preventDefault();
            pay();
          }}
        >
          <label className="field">
            รับเงินมา
            <input
              className="cash-input"
              inputMode="decimal"
              autoFocus
              value={cash}
              onKeyDown={submitOnEnter(() => pay())}
              onChange={(e) => {
                setCash(e.target.value.replace(/[^\d.]/g, ''));
                setError('');
              }}
            />
          </label>
          <div className="quick-cash">
            <button type="button" className="btn" onClick={() => pay(totalSatang)}>
              พอดี
            </button>
            {quickAmounts(totalSatang).map((amount) => (
              <button type="button" className="btn" key={amount} onClick={() => setCash(String(amount / 100))}>
                {baht(amount)}
              </button>
            ))}
          </div>
          <div className={`change ${cash !== '' && change < 0 ? 'text-danger' : ''}`}>
            <span>เงินทอน</span>
            <span className="total">{cash === '' ? '–' : change < 0 ? `ขาด ${baht(-change)}` : baht(change)}</span>
          </div>
          {error && <p className="form-error">{error}</p>}
          <div className="modal-actions">
            <button type="button" className="btn" onClick={onClose}>
              กลับไปแก้บิล <kbd>Esc</kbd>
            </button>
            <button className="btn primary" disabled={busy}>
              {busy ? 'กำลังบันทึก…' : 'รับเงินและบันทึก'} <kbd>Enter</kbd>
            </button>
          </div>
        </form>
      ) : (
        <div className="stack">
          <div className="qr-box">
            {!promptpayEnabled && <p className="muted">ยังไม่ได้ตั้งค่าพร้อมเพย์ของร้าน (ตั้งได้ที่หลังร้าน → ข้อมูลร้าน)</p>}
            {promptpayEnabled && !qr && <p className="muted">กำลังสร้าง QR…</p>}
            {qr?.error && <p className="form-error">{qr.error}</p>}
            {qr?.payload && (
              <>
                <QRCodeSVG value={qr.payload} size={200} marginSize={2} />
                <p className="muted small">พร้อมเพย์ {qr.account} · {baht(totalSatang)} บาท</p>
              </>
            )}
          </div>
          <p className="small">ให้ลูกค้าสแกนจ่าย แล้วตรวจว่าเงินเข้าบัญชีร้านจริงก่อนกดยืนยัน</p>
          {error && <p className="form-error">{error}</p>}
          <div className="modal-actions">
            <button type="button" className="btn" onClick={onClose}>
              กลับไปแก้บิล <kbd>Esc</kbd>
            </button>
            <button type="button" className="btn primary" disabled={busy} onClick={() => pay()}>
              {busy ? 'กำลังบันทึก…' : 'ได้รับเงินแล้ว บันทึกบิล'}
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}
