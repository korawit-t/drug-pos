export const VIEWS = { pos: '#/', receive: '#/receive' };

export const viewFromHash = () => (window.location.hash === VIEWS.receive ? 'receive' : 'pos');

export function Brand({ name }) {
  return (
    <div className="brand">
      <span className="brand-mark" aria-hidden="true">
        +
      </span>
      <strong>{name}</strong>
    </div>
  );
}

export function ViewTabs({ nav }) {
  const tab = (view, label) => (
    <a href={VIEWS[view]} className={nav.view === view ? 'active' : ''} aria-current={nav.view === view ? 'page' : undefined}>
      {label}
    </a>
  );
  return (
    <nav className="view-tabs" aria-label="หน้าจอ">
      {tab('pos', 'ขายหน้าร้าน')}
      {tab('receive', 'รับยาเข้า')}
    </nav>
  );
}

export function TopLinks({ nav }) {
  return (
    <div className="top-links">
      <a href="/reports/">รายงาน</a>
      {nav.me.is_staff && <a href="/admin/">หลังร้าน</a>}
      <span className="muted">{nav.me.name}</span>
      <button type="button" className="btn small" onClick={nav.onLogout}>
        ออกจากระบบ
      </button>
    </div>
  );
}
