import { useEffect, useState } from 'react';
import { api, UNAUTHORIZED_EVENT } from './api.js';
import Login from './Login.jsx';
import Pos from './pos/Pos.jsx';

export default function App() {
  const [me, setMe] = useState(undefined); // undefined: checking, null: logged out

  useEffect(() => {
    api('/auth/csrf')
      .then(() => api('/auth/me'))
      .then(setMe)
      .catch(() => setMe(null));
    const onUnauthorized = () => setMe(null);
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  if (me === undefined) return <div className="boot">กำลังโหลด…</div>;
  if (!me) return <Login onLogin={setMe} />;

  async function logout() {
    await api('/auth/logout', { method: 'POST' }).catch(() => {});
    setMe(null);
  }
  return <Pos me={me} onLogout={logout} />;
}
