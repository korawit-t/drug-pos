import { assign, fieldAt, mappedCount, missingRequired } from './mapping.js';

// The file's own columns, with what each one means above the data it holds —
// so the person is looking at the rows while they decide.
export default function ColumnMapper({ preview, mapping, onChange, onHeaderRow, busy }) {
  const { headers, sample, fields, header_row: headerRow, data_rows: dataRows } = preview;
  const missing = missingRequired(mapping, fields);
  const used = mappedCount(mapping);

  return (
    <div className="panel">
      <div className="receipt-title">
        <h2>จับคู่คอลัมน์</h2>
        <span className="muted small">
          อ่านได้ {dataRows.toLocaleString('th-TH')} แถว · จับคู่แล้ว {used} จาก {headers.length} คอลัมน์
        </span>
      </div>
      <p className="muted small">
        ระบบเดาให้จากชื่อคอลัมน์ ถ้าเดาผิดหรือเดาไม่ออกให้เลือกเองได้ที่หัวตารางข้างล่าง — คอลัมน์ที่ไม่ใช้เลือก "ไม่ใช้"
      </p>

      <label className="field-inline">
        หัวตารางอยู่แถวที่
        <input
          type="number"
          min={1}
          value={headerRow}
          disabled={busy}
          aria-label="แถวที่เป็นหัวตาราง"
          style={{ width: '5em' }}
          onChange={(e) => onHeaderRow(Number(e.target.value) || 1)}
        />
        <span className="muted small">เปลี่ยนเมื่อไฟล์มีบรรทัดชื่อรายงานหลายบรรทัดข้างบน</span>
      </label>

      {missing.length > 0 && (
        <div className="alert warning">
          ยังไม่ได้บอกว่าคอลัมน์ไหนคือ <strong>{missing.map((f) => f.label).join(', ')}</strong> — ต้องเลือกให้ครบก่อนนำเข้า
        </div>
      )}

      <div className="map-scroll">
        <table className="cart map-table">
          <thead>
            <tr>
              {headers.map((header, index) => {
                const field = fieldAt(mapping, index);
                return (
                  <th key={index}>
                    <select
                      value={field}
                      disabled={busy}
                      aria-label={`คอลัมน์ ${header || index + 1} คือข้อมูลอะไร`}
                      className={field ? 'mapped' : ''}
                      onChange={(e) => onChange(assign(mapping, index, e.target.value))}
                    >
                      <option value="">— ไม่ใช้ —</option>
                      {fields.map((f) => (
                        <option key={f.name} value={f.name}>
                          {f.label}
                          {f.required ? ' *' : ''}
                        </option>
                      ))}
                    </select>
                    <div className="file-header" title={fields.find((f) => f.name === field)?.help || ''}>
                      {header || <span className="muted">(ไม่มีชื่อ)</span>}
                    </div>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {sample.map((row, index) => (
              <tr key={index}>
                {headers.map((_, column) => (
                  <td key={column} className={fieldAt(mapping, column) ? '' : 'unused'}>
                    {row[column]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {sample.length < dataRows && (
        <p className="muted small">แสดง {sample.length} แถวแรกจาก {dataRows.toLocaleString('th-TH')} แถว</p>
      )}
    </div>
  );
}
