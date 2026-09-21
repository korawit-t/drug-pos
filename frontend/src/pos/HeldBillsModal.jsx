import { useEffect, useState } from 'react';
import { api } from '../api.js';
import { timeOf } from '../format.js';
import { Modal } from './ui.jsx';

export default function HeldBillsModal({ onResume, onClose }) {
  const [bills, setBills] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api('/held-bills')
      .then(setBills)
      .catch((err) => setError(err.message));
  }, []);

  return (
    <Modal title="บิลที่พักไว้" onClose={onClose} width={560}>
      {error && <p className="form-error">{error}</p>}
      {bills === null && !error && <p className="muted">กำลังโหลด…</p>}
      {bills?.length === 0 && <p className="muted">ไม่มีบิลที่พักไว้</p>}
      <ul className="pick-list">
        {bills?.map((b) => (
          <li key={b.id} onClick={() => onResume(b)}>
            <div>
              <strong>{b.label || 'ไม่มีชื่อ'}</strong>
              <div className="muted small">
                {timeOf(b.created_at)} · {b.payload.lines.length} รายการ · พักโดย {b.created_by}
              </div>
            </div>
            <span className="btn small">เรียกกลับมา</span>
          </li>
        ))}
      </ul>
    </Modal>
  );
}
