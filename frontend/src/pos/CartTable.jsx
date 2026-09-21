import { baht, daysBetween, thaiDate } from '../format.js';
import { lineTotalSatang, lineUnit, unitPriceSatang } from './bill.js';
import { CategoryBadge } from './ui.jsx';

function LotHint({ plan, product, today, nearExpiryDays }) {
  if (!plan || plan.allocations.length === 0) return null;
  const first = plan.allocations[0];
  const near = daysBetween(today, first.expiry_date) <= nearExpiryDays;
  return (
    <div className="lot-hint">
      lot {first.lot_no} · หมดอายุ {thaiDate(first.expiry_date, 'month')}
      {plan.allocations.length > 1 && ` + อีก ${plan.allocations.length - 1} lot`}
      {near && <span className="badge amber small">ใกล้หมดอายุ</span>}
      {product.expired > 0 && <span className="muted"> · มีของหมดอายุ {product.expired} {product.base_unit} (ไม่ขาย)</span>}
    </div>
  );
}

function Status({ line, plan }) {
  if (plan && plan.short > 0) {
    return <span className="badge red">สต็อกไม่พอ ขาด {plan.short} {line.product.base_unit}</span>;
  }
  if (!line.product.needs_pharmacist) return null;
  if (line.approval) return <span className="badge green">ยืนยันแล้ว · {line.approval.by}</span>;
  return <span className="badge amber">รอเภสัชกรยืนยัน</span>;
}

export default function CartTable({ bill, plan, meta, dispatch }) {
  if (bill.lines.length === 0) {
    return (
      <div className="cart-empty">
        <p>ยังไม่มีรายการ</p>
        <p className="muted">สแกนบาร์โค้ด หรือพิมพ์ชื่อยาในช่องค้นหาด้านบน</p>
      </div>
    );
  }
  return (
    <table className="cart">
      <thead>
        <tr>
          <th className="col-no">#</th>
          <th>รายการ</th>
          <th className="col-qty">จำนวน</th>
          <th className="col-unit">หน่วย</th>
          <th className="col-num">ราคา/หน่วย</th>
          <th className="col-num">รวม</th>
          <th className="col-status">สถานะ</th>
          <th className="col-del" aria-label="ลบ" />
        </tr>
      </thead>
      <tbody>
        {bill.lines.map((line, i) => {
          const unit = lineUnit(line);
          return (
            <tr
              key={line.key}
              className={line.key === bill.selectedKey ? 'selected' : ''}
              onClick={() => dispatch({ type: 'select', key: line.key })}
            >
              <td className="col-no">{i + 1}</td>
              <td>
                <div className="line-name">
                  {line.product.display_name} <CategoryBadge product={line.product} />
                </div>
                {line.product.generic_name && <div className="muted small">{line.product.generic_name}</div>}
                <LotHint
                  plan={plan[line.key]}
                  product={line.product}
                  today={meta.today}
                  nearExpiryDays={meta.near_expiry_days}
                />
              </td>
              <td className="col-qty">
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={line.qty}
                  aria-label="จำนวน"
                  onChange={(e) => {
                    const qty = Math.max(1, Math.floor(Number(e.target.value) || 1));
                    dispatch({ type: 'update', key: line.key, changes: { qty } });
                  }}
                />
              </td>
              <td className="col-unit">
                <select
                  value={line.unitId}
                  aria-label="หน่วย"
                  onChange={(e) => dispatch({ type: 'update', key: line.key, changes: { unitId: Number(e.target.value) } })}
                >
                  {line.product.units.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.name}
                      {u.factor > 1 ? ` (${u.factor})` : ''}
                    </option>
                  ))}
                </select>
                {unit.factor > 1 && (
                  <div className="muted small">
                    = {line.qty * unit.factor} {line.product.base_unit}
                  </div>
                )}
              </td>
              <td className="col-num">{baht(unitPriceSatang(line, bill.priceLevel))}</td>
              <td className="col-num strong">{baht(lineTotalSatang(line, bill.priceLevel))}</td>
              <td className="col-status">
                <Status line={line} plan={plan[line.key]} />
              </td>
              <td className="col-del">
                <button
                  type="button"
                  className="icon-btn"
                  aria-label={`ลบ ${line.product.display_name}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    dispatch({ type: 'remove', key: line.key });
                  }}
                >
                  ×
                </button>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
