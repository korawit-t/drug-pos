import { useRef, useState } from 'react';
import { api } from '../api.js';
import { bahtOf } from '../format.js';
import { CategoryBadge } from './ui.jsx';

function defaultUnit(product) {
  return product.units.find((u) => u.id === product.matched_unit_id) || product.units.find((u) => u.is_default) || product.units[0];
}

export default function SearchBox({
  inputRef,
  priceLevel = 1,
  showPrice = true,
  placeholder = 'สแกนบาร์โค้ด หรือพิมพ์ชื่อยา / ชื่อสามัญ',
  onPick,
  onEmptyKey,
  onNotFound,
}) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState({ query: '', items: [] });
  const [active, setActive] = useState(0);
  const seq = useRef(0);
  const timer = useRef(null);

  const open = query.trim() !== '' && results.items.length > 0;

  async function search(text) {
    const id = ++seq.current;
    const items = await api('/products/search', { params: { q: text } });
    if (id !== seq.current) return null; // a newer search is on its way
    setResults({ query: text, items });
    setActive(0);
    return items;
  }

  function clear() {
    clearTimeout(timer.current);
    seq.current++;
    setQuery('');
    setResults({ query: '', items: [] });
  }

  function pick(product) {
    onPick(product, product.matched_unit_id);
    clear();
  }

  function onChange(e) {
    const text = e.target.value;
    setQuery(text);
    clearTimeout(timer.current);
    if (!text.trim()) {
      seq.current++;
      setResults({ query: '', items: [] });
      return;
    }
    timer.current = setTimeout(() => search(text.trim()).catch(() => {}), 200);
  }

  async function onKeyDown(e) {
    if (!query) {
      if (onEmptyKey(e)) e.preventDefault();
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((i) => Math.min(i + 1, results.items.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Escape') {
      e.preventDefault();
      clear();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      clearTimeout(timer.current);
      const text = query.trim();
      // A barcode scanner types the whole code and presses Enter before the
      // debounced search runs — never act on results for an older query.
      let items = results.query === text ? results.items : null;
      let index = active;
      if (items === null) {
        items = await search(text).catch(() => []);
        index = 0;
        if (items === null) return;
      }
      if (items.length === 0) {
        onNotFound(text);
        clear();
      } else {
        pick(items[index] || items[0]);
      }
    }
  }

  return (
    <div className="search">
      <span className="search-icon" aria-hidden="true">⌕</span>
      <input
        ref={inputRef}
        className="search-input"
        value={query}
        onChange={onChange}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        aria-label="ค้นหาสินค้า"
        autoComplete="off"
        spellCheck="false"
      />
      {open && (
        <ul className="search-results" role="listbox">
          {results.items.map((p, i) => {
            const unit = defaultUnit(p);
            return (
              <li
                key={p.id}
                role="option"
                aria-selected={i === active}
                className={i === active ? 'active' : ''}
                onMouseEnter={() => setActive(i)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  pick(p);
                }}
              >
                <div className="result-main">
                  <span className="result-name">{p.display_name}</span>
                  {p.generic_name && <span className="muted"> · {p.generic_name}</span>}
                  <div className="result-meta">
                    <CategoryBadge product={p} />
                    <span className={p.available ? 'muted' : 'text-danger'}>
                      {p.available ? `คงเหลือ ${p.available} ${p.base_unit}` : 'ไม่มีสต็อกที่ขายได้'}
                    </span>
                    {p.expired > 0 && <span className="text-danger">หมดอายุ {p.expired} {p.base_unit}</span>}
                    {p.storage_location && <span className="muted">{p.storage_location}</span>}
                  </div>
                </div>
                {showPrice && (
                  <div className="result-price">
                    {bahtOf(unit.prices[priceLevel - 1])}
                    <span className="muted"> / {unit.name}</span>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
