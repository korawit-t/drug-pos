import { useEffect, useState } from 'react';
import { api, UNAUTHORIZED_EVENT } from './api.js';
import Login from './Login.jsx';
import { viewFromHash } from './nav.jsx';
import Pos from './pos/Pos.jsx';
import Receive from './receive/Receive.jsx';
import ImportData from './setup/Import.jsx';

export default function App() {
  const [me, setMe] = useState(undefined); // undefined: checking, null: logged out
  const [meta, setMeta] = useState(null);
  const [metaError, setMetaError] = useState('');
  const [view, setView] = useState(viewFromHash);
  // Screens stay mounted once opened, so switching away never loses a half-entered bill.
  const [opened, setOpened] = useState(() => new Set([viewFromHash()]));

  useEffect(() => {
    api('/auth/csrf')
      .then(() => api('/auth/me'))
      .then(setMe)
      .catch(() => setMe(null));
    const onUnauthorized = () => setMe(null);
    const onHashChange = () => {
      const next = viewFromHash();
      setView(next);
      setOpened((prev) => new Set(prev).add(next));
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    window.addEventListener('hashchange', onHashChange);
    return () => {
      window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
      window.removeEventListener('hashchange', onHashChange);
    };
  }, []);

  // Reloaded on every screen switch too, so "today" stays right on a counter left open overnight.
  useEffect(() => {
    if (!me) return;
    api('/meta')
      .then((data) => {
        setMeta(data);
        setMetaError('');
      })
      .catch((err) => setMetaError(err.message));
  }, [me, view]);

  if (me === undefined) return <div className="boot">กำลังโหลด…</div>;
  if (!me) return <Login onLogin={setMe} />;
  if (!meta) return <div className="boot">{metaError || 'กำลังโหลดข้อมูลร้าน…'}</div>;

  async function logout() {
    await api('/auth/logout', { method: 'POST' }).catch(() => {});
    setMe(null);
    setMeta(null);
  }
  const nav = { view, me, onLogout: logout };

  return (
    <>
      <Pos meta={meta} nav={nav} active={view === 'pos'} />
      {opened.has('receive') && <Receive meta={meta} nav={nav} active={view === 'receive'} />}
      {opened.has('import') && <ImportData meta={meta} nav={nav} active={view === 'import'} />}
    </>
  );
}
