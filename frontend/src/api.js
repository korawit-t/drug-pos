export class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

function cookie(name) {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : '';
}

export const UNAUTHORIZED_EVENT = 'drugpos:unauthorized';

export async function api(path, { method = 'GET', body, params } = {}) {
  let url = `/api${path}`;
  if (params) url += `?${new URLSearchParams(params)}`;
  const res = await fetch(url, {
    method,
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': cookie('csrftoken') },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401 && path !== '/auth/me' && path !== '/auth/login') {
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    }
    const detail = data?.detail;
    const message = typeof detail === 'string' ? detail : detail ? 'ข้อมูลที่ส่งไม่ถูกต้อง' : `เกิดข้อผิดพลาด (${res.status})`;
    throw new ApiError(message, res.status, data);
  }
  return data;
}
