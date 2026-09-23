import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { api } from '../api.js';
import { bahtOf } from '../format.js';
import { Brand, TopLinks, ViewTabs } from '../nav.jsx';
import { labelsUrl, printPage, receiptUrl } from '../print.js';
import AllergyModal from './AllergyModal.jsx';
import { billFromHeld, billNeeds, billReducer, billTotalSatang, heldPayload, newBill, planStock } from './bill.js';
import CartTable from './CartTable.jsx';
import CustomerModal from './CustomerModal.jsx';
import HeldBillsModal from './HeldBillsModal.jsx';
import PaymentModal from './PaymentModal.jsx';
import PharmacistModal from './PharmacistModal.jsx';
import SalesTodayModal from './SalesTodayModal.jsx';
import SearchBox from './SearchBox.jsx';
import SidePanel from './SidePanel.jsx';
import { Toast, usePersistentState, useToast } from './ui.jsx';

const FKEYS = [
  ['F2', 'ลูกค้า'],
  ['F3', 'บิลที่พัก'],
  ['F4', 'บิลวันนี้'],
  ['F8', 'เภสัชกรยืนยัน'],
  ['F9', 'บิลใหม่'],
  ['F10', 'พักบิล'],
  ['F11', 'พิมพ์ฉลากบิลล่าสุด'],
  ['F12', 'ชำระเงิน'],
];

export default function Pos({ meta, nav, active }) {
  const [bill, dispatch] = useReducer(billReducer, undefined, newBill);
  const [modal, setModal] = useState(null);
  const [summary, setSummary] = useState(null);
  const [lastSale, setLastSale] = useState(null);
  const [toast, notify] = useToast();
  const [printPrefs, setPrintPrefs] = usePersistentState('drugpos.print', { receipt: false, labels: false });
  const searchRef = useRef(null);
  const activeRef = useRef(active);
  activeRef.current = active;

  const plan = useMemo(() => planStock(bill.lines), [bill.lines]);
  const totalSatang = billTotalSatang(bill);

  // Allergy alerts for the bill's customer, re-checked whenever the customer,
  // the products in the bill, or the customer's allergy records change.
  const [alerts, setAlerts] = useState({});
  const [allergyVersion, setAllergyVersion] = useState(0);
  const customerId = bill.customer?.id ?? null;
  const productIds = useMemo(
    () => [...new Set(bill.lines.map((l) => l.product.id))].sort((a, b) => a - b).join(','),
    [bill.lines],
  );
  useEffect(() => {
    if (!customerId || !productIds) {
      setAlerts({});
      return undefined;
    }
    let current = true;
    api(`/customers/${customerId}/allergy-check`, { params: { product_ids: productIds } })
      .then((result) => current && setAlerts(result.alerts))
      .catch(() => {});
    return () => {
      current = false;
    };
  }, [customerId, productIds, allergyVersion]);
  useEffect(() => {
    dispatch({ type: 'syncAllergyApprovals', productIds: Object.keys(alerts).map(Number), customerId });
  }, [alerts, customerId]);
  const alertCount = bill.lines.filter((l) => alerts[l.product.id]?.length).length;

  const refreshSummary = useCallback(() => {
    api('/sales/summary').then(setSummary).catch(() => {});
  }, []);

  useEffect(() => {
    if (active) refreshSummary();
  }, [active, refreshSummary]);

  useEffect(() => {
    if (active && !modal) searchRef.current?.focus();
  }, [active, modal]);

  function addProduct(product, unitId) {
    if (product.available <= 0) {
      notify(
        product.expired > 0
          ? `${product.display_name}: เหลือแต่ของหมดอายุ ขายไม่ได้`
          : `${product.display_name}: ไม่มีสต็อก`,
        'error',
      );
      return;
    }
    dispatch({ type: 'add', product, unitId });
  }

  function startPayment() {
    if (!bill.lines.length) return;
    const short = bill.lines.find((l) => plan[l.key]?.short > 0);
    if (short) {
      notify(`${short.product.display_name}: สต็อกไม่พอ`, 'error');
      return;
    }
    setModal(billNeeds(bill, alerts).pending.length ? 'pharmacist-then-pay' : 'payment');
  }

  function openPharmacist() {
    if (!billNeeds(bill, alerts).pending.length) {
      notify('ไม่มีรายการที่รอเภสัชกรยืนยัน');
      return;
    }
    setModal('pharmacist');
  }

  async function holdBill() {
    if (!bill.lines.length) {
      notify('ไม่มีรายการให้พัก');
      return;
    }
    const label = bill.customer?.name || bill.buyerName || bill.lines[0].product.display_name;
    try {
      await api('/held-bills', { method: 'POST', body: { label, payload: heldPayload(bill) } });
      dispatch({ type: 'reset' });
      setModal(null);
      notify(`พักบิลแล้ว: ${label}`);
    } catch (err) {
      notify(err.message, 'error');
    }
  }

  async function resumeBill(held) {
    if (bill.lines.length) {
      notify('พักหรือล้างบิลปัจจุบันก่อน แล้วค่อยเรียกบิลที่พักกลับมา', 'error');
      return;
    }
    try {
      const ids = [...new Set(held.payload.lines.map((l) => l.productId))].join(',');
      const products = ids ? await api('/products', { params: { ids } }) : [];
      // The customer as they are now — allergies may have been recorded since the bill was held.
      const customer = held.payload.customer ? await api(`/customers/${held.payload.customer.id}`) : null;
      dispatch({ type: 'load', bill: billFromHeld({ ...held.payload, customer }, products) });
      await api(`/held-bills/${held.id}`, { method: 'DELETE' });
      setModal(null);
      notify(`เรียกบิลกลับมาแล้ว: ${held.label}`);
    } catch (err) {
      notify(err.message, 'error');
    }
  }

  function newBillConfirmed() {
    if (bill.lines.length && !window.confirm('ล้างบิลปัจจุบันแล้วเริ่มบิลใหม่?')) return;
    dispatch({ type: 'reset' });
  }

  async function printLastLabels(sale = lastSale) {
    if (!sale) {
      notify('ยังไม่มีบิลล่าสุด');
      return;
    }
    await printPage(labelsUrl(sale.id));
  }

  async function onPaid(sale) {
    setModal(null);
    setLastSale(sale);
    dispatch({ type: 'reset' });
    refreshSummary();
    notify(`บันทึกบิล ${sale.number} แล้ว`);
    if (printPrefs.receipt) await printPage(receiptUrl(sale.id));
    if (printPrefs.labels && sale.items.some((i) => i.category !== 'general')) await printPage(labelsUrl(sale.id));
    searchRef.current?.focus();
  }

  function onEmptySearchKey(e) {
    const selected = bill.lines.find((l) => l.key === bill.selectedKey);
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      dispatch({ type: 'moveSelection', delta: e.key === 'ArrowDown' ? 1 : -1 });
      return true;
    }
    if (!selected) return false;
    if (e.key === '+' || e.key === '-') {
      const qty = Math.max(1, selected.qty + (e.key === '+' ? 1 : -1));
      dispatch({ type: 'update', key: selected.key, changes: { qty } });
      return true;
    }
    if (e.key === 'Delete') {
      dispatch({ type: 'remove', key: selected.key });
      return true;
    }
    return false;
  }

  // Function keys work from anywhere on the sales screen, except inside dialogs.
  // Any other typing outside a form field goes to the search box, so a barcode
  // scan still lands in the right place after someone clicks around.
  const keyHandlers = useRef();
  keyHandlers.current = {
    F2: () => setModal('customer'),
    F3: () => setModal('held'),
    F4: () => setModal('sales'),
    F8: openPharmacist,
    F9: newBillConfirmed,
    F10: holdBill,
    F11: () => printLastLabels(),
    F12: startPayment,
  };
  useEffect(() => {
    const onKey = (e) => {
      if (!activeRef.current) return;
      const modalOpen = document.querySelector('.modal-backdrop');
      const handler = keyHandlers.current[e.key];
      if (!handler) {
        const el = document.activeElement;
        const inField = el && ['INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName);
        if (!modalOpen && !inField && e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
          searchRef.current?.focus();
        }
        return;
      }
      e.preventDefault();
      if (!modalOpen) handler();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <div className="pos" hidden={!active}>
      <header className="topbar">
        <Brand name={meta.shop.name} />
        <ViewTabs nav={nav} />
        <SearchBox
          inputRef={searchRef}
          priceLevel={bill.priceLevel}
          onPick={addProduct}
          onEmptyKey={onEmptySearchKey}
          onNotFound={(q) => notify(`ไม่พบสินค้า "${q}"`, 'error')}
        />
        <TopLinks nav={nav} />
      </header>

      {lastSale && (
        <div className="last-sale">
          <span>
            บิลล่าสุด <strong>{lastSale.number}</strong> · รวม {bahtOf(lastSale.total)}
            {lastSale.change !== null && (
              <>
                {' '}
                · เงินทอน <strong className="change-amount">{bahtOf(lastSale.change)}</strong>
              </>
            )}
          </span>
          <span className="row-actions">
            <button type="button" className="btn small" onClick={() => printPage(receiptUrl(lastSale.id))}>
              พิมพ์ใบเสร็จ
            </button>
            <button type="button" className="btn small" onClick={() => printLastLabels(lastSale)}>
              พิมพ์ฉลาก
            </button>
            <button type="button" className="icon-btn" aria-label="ซ่อน" onClick={() => setLastSale(null)}>
              ×
            </button>
          </span>
        </div>
      )}

      <main className="workspace">
        <section className="cart-column">
          {alertCount > 0 && (
            <div className="allergy-banner" role="alert">
              <strong>ลูกค้ามีประวัติแพ้ยา</strong> ตรงกับ {alertCount} รายการในบิล — ต้องให้เภสัชกรตรวจและยืนยันก่อนจ่าย
            </div>
          )}
          <div className="cart-area">
            <CartTable bill={bill} plan={plan} meta={meta} alerts={alerts} dispatch={dispatch} />
          </div>
        </section>
        <SidePanel
          bill={bill}
          meta={meta}
          totalSatang={totalSatang}
          dispatch={dispatch}
          onPickCustomer={() => setModal('customer')}
          onAddAllergy={() => setModal('allergy')}
          onPay={startPayment}
          printPrefs={printPrefs}
          setPrintPrefs={setPrintPrefs}
        />
      </main>

      <footer className="footer">
        <div className="fkeys">
          {FKEYS.map(([key, label]) => (
            <button type="button" key={key} className="fkey" onClick={() => keyHandlers.current[key]()}>
              <kbd>{key}</kbd> {label}
            </button>
          ))}
        </div>
        {summary && (
          <div className="summary">
            วันนี้ {summary.count} บิล · ยอดขาย <strong>{bahtOf(summary.total)}</strong> · เงินสด{' '}
            {bahtOf(summary.cash)} · โอน {bahtOf(summary.transfer)}
          </div>
        )}
      </footer>

      <Toast toast={toast} />

      {modal === 'customer' && (
        <CustomerModal
          meta={meta}
          onClose={() => setModal(null)}
          onSelect={(customer) => {
            dispatch({ type: 'setCustomer', customer });
            setModal(null);
          }}
        />
      )}
      {(modal === 'pharmacist' || modal === 'pharmacist-then-pay') && (
        <PharmacistModal
          bill={bill}
          plan={plan}
          meta={meta}
          alerts={alerts}
          dispatch={dispatch}
          onClose={(action) => (action === 'hold' ? holdBill() : setModal(null))}
          onApproved={() => {
            if (modal === 'pharmacist-then-pay') setModal('payment');
            else {
              setModal(null);
              notify('เภสัชกรยืนยันแล้ว');
            }
          }}
        />
      )}
      {modal === 'payment' && (
        <PaymentModal
          bill={bill}
          totalSatang={totalSatang}
          promptpayEnabled={meta.promptpay_enabled}
          onClose={() => setModal(null)}
          onPaid={onPaid}
          onApprovalExpired={(message) => {
            dispatch({ type: 'clearApprovals' });
            setModal(null);
            notify(`${message} — ให้เภสัชกรยืนยันใหม่ (F8)`, 'error');
          }}
        />
      )}
      {modal === 'allergy' && bill.customer && (
        <AllergyModal
          customer={bill.customer}
          onClose={() => setModal(null)}
          onSaved={(customer) => {
            dispatch({ type: 'updateCustomer', customer });
            setAllergyVersion((v) => v + 1);
            setModal(null);
            notify('บันทึกประวัติแพ้ยาแล้ว');
          }}
        />
      )}
      {modal === 'held' && <HeldBillsModal onClose={() => setModal(null)} onResume={resumeBill} />}
      {modal === 'sales' && <SalesTodayModal meta={meta} onClose={() => setModal(null)} onChanged={refreshSummary} />}
    </div>
  );
}
