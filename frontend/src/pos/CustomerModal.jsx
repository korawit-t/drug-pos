import { useEffect, useState } from 'react';
import { api } from '../api.js';
import { Modal } from './ui.jsx';

export default function CustomerModal({ meta, onSelect, onClose }) {
  const [query, setQuery] = useState('');
  const [customers, setCustomers] = useState([]);
  const [active, setActive] = useState(0);

  useEffect(() => {
    const timer = setTimeout(() => {
      api('/customers', { params: { q: query } })
        .then((list) => {
          setCustomers(list);
          setActive(0);
        })
        .catch(() => {});
    }, 150);
    return () => clearTimeout(timer);
  }, [query]);

  const levelName = (level) => meta.price_levels.find((p) => p.level === level)?.name ?? level;

  function onKeyDown(e) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((i) => Math.min(i + 1, customers.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter' && customers[active]) {
      e.preventDefault();
      onSelect(customers[active]);
    }
  }

  return (
    <Modal title="เลือกลูกค้า" onClose={onClose} width={620}>
      <div className="stack">
        <input
          autoFocus
          placeholder="ชื่อ หรือเบอร์โทร"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
        />
        <button type="button" className="btn" onClick={() => onSelect(null)}>
          ลูกค้าทั่วไป (ราคาระดับ 1)
        </button>
        <ul className="pick-list">
          {customers.map((c, i) => (
            <li key={c.id} className={i === active ? 'active' : ''} onMouseEnter={() => setActive(i)} onClick={() => onSelect(c)}>
              <div>
                <strong>{c.name}</strong> <span className="muted small">{c.phone}</span>
                {c.allergies && <div className="text-danger small">แพ้ยา: {c.allergies}</div>}
              </div>
              <span className="badge neutral">
                ราคา {c.price_level} · {levelName(c.price_level)}
              </span>
            </li>
          ))}
          {customers.length === 0 && <li className="muted">ไม่พบลูกค้า (เพิ่มลูกค้าได้ที่หลังร้าน)</li>}
        </ul>
      </div>
    </Modal>
  );
}
