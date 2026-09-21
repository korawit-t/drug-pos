import { useEffect, useState } from 'react';

export function Modal({ title, onClose, children, footer, width = 560 }) {
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ width }} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head">
          <h2>{title}</h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="ปิด">
            ×
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

const CATEGORY_STYLE = {
  general: 'neutral',
  household: 'green',
  ready_packed: 'neutral',
  dangerous: 'amber',
  special_controlled: 'red',
};

export function CategoryBadge({ product }) {
  return <span className={`badge ${CATEGORY_STYLE[product.category] || 'neutral'}`}>{product.category_label}</span>;
}

export function PharmacistPicker({ pharmacists, value, onChange }) {
  if (!pharmacists.length) return <p className="form-error">ยังไม่มีผู้ใช้ที่เป็นเภสัชกร (เพิ่มได้ที่หลังร้าน)</p>;
  return (
    <div className="pharmacist-picker" role="radiogroup" aria-label="เภสัชกร">
      {pharmacists.map((p) => (
        <button
          type="button"
          key={p.id}
          role="radio"
          aria-checked={value === p.id}
          className={`chip ${value === p.id ? 'active' : ''}`}
          onClick={() => onChange(p.id)}
          disabled={!p.has_pin}
          title={p.has_pin ? '' : 'ยังไม่ได้ตั้ง PIN'}
        >
          {p.name}
          {!p.has_pin && ' (ยังไม่ตั้ง PIN)'}
        </button>
      ))}
    </div>
  );
}

// Enter in the key field of a dialog (PIN, cash received) always submits,
// without relying on the browser's implicit form submission.
export const submitOnEnter = (submit) => (e) => {
  if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
    e.preventDefault();
    submit(e);
  }
};

const LAST_PHARMACIST = 'drugpos.lastPharmacist';

export function useLastPharmacist(pharmacists) {
  const [id, setId] = useState(() => {
    const saved = Number(safeGet(LAST_PHARMACIST));
    const usable = pharmacists.filter((p) => p.has_pin);
    return usable.some((p) => p.id === saved) ? saved : usable[0]?.id ?? null;
  });
  const remember = (value) => {
    setId(value);
    safeSet(LAST_PHARMACIST, String(value));
  };
  return [id, remember];
}

export function usePersistentState(key, initial) {
  const [value, setValue] = useState(() => {
    try {
      const raw = safeGet(key);
      return raw ? { ...initial, ...JSON.parse(raw) } : initial;
    } catch {
      return initial;
    }
  });
  const update = (next) => {
    setValue(next);
    safeSet(key, JSON.stringify(next));
  };
  return [value, update];
}

function safeGet(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeSet(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // private mode or storage disabled — preferences just won't stick
  }
}
