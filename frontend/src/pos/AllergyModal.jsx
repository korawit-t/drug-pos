import { useEffect, useState } from 'react';
import { api } from '../api.js';
import { Modal } from './ui.jsx';

const SEVERITIES = [
  ['unknown', 'ไม่ทราบความรุนแรง'],
  ['mild', 'ไม่รุนแรง'],
  ['severe', 'รุนแรง (เช่น SJS หายใจลำบาก ช็อก)'],
];

// Record an allergy right at the counter, while the pharmacist is talking to the customer.
export default function AllergyModal({ customer, onSaved, onClose }) {
  const [groups, setGroups] = useState([]);
  const [allergenId, setAllergenId] = useState('');
  const [substance, setSubstance] = useState('');
  const [reaction, setReaction] = useState('');
  const [severity, setSeverity] = useState('unknown');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api('/allergens')
      .then(setGroups)
      .catch((err) => setError(err.message));
  }, []);

  async function submit(e) {
    e.preventDefault();
    if (!allergenId && !substance.trim()) {
      setError('ระบุยาที่แพ้ หรือเลือกกลุ่มยา');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const updated = await api(`/customers/${customer.id}/allergies`, {
        method: 'POST',
        body: { allergen_id: allergenId ? Number(allergenId) : null, substance, reaction, severity },
      });
      onSaved(updated);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={`บันทึกประวัติแพ้ยา · ${customer.name}`} onClose={onClose} width={560}>
      <form className="stack" onSubmit={submit}>
        <label className="field">
          ยาที่แพ้
          <input
            autoFocus
            value={substance}
            placeholder="Amoxicillin"
            onChange={(e) => {
              setSubstance(e.target.value);
              setError('');
            }}
          />
        </label>
        <label className="field">
          กลุ่มยา (ถ้ารู้)
          <select value={allergenId} onChange={(e) => setAllergenId(e.target.value)}>
            <option value="">— ให้ระบบจับคู่จากชื่อยา —</option>
            {groups.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </select>
          <span className="muted small">ระบบจะเตือนยาทุกตัวในกลุ่มเดียวกัน และกลุ่มที่อาจแพ้ข้ามกัน</span>
        </label>
        <label className="field">
          อาการ
          <input value={reaction} placeholder="ผื่นลมพิษ" onChange={(e) => setReaction(e.target.value)} />
        </label>
        <label className="field">
          ความรุนแรง
          <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
            {SEVERITIES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        {error && <p className="form-error">{error}</p>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>
            ยกเลิก
          </button>
          <button className="btn primary" disabled={busy}>
            {busy ? 'กำลังบันทึก…' : 'บันทึก'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
