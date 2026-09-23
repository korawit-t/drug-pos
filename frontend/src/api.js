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

async function unwrap(res, path) {
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

export async function api(path, { method = 'GET', body, params } = {}) {
  let url = `/api${path}`;
  if (params) url += `?${new URLSearchParams(params)}`;
  const res = await fetch(url, {
    method,
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': cookie('csrftoken') },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return unwrap(res, path);
}

// Multipart upload: the browser sets Content-Type (with the boundary) itself.
export async function upload(path, formData) {
  const res = await fetch(`/api${path}`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'X-CSRFToken': cookie('csrftoken') },
    body: formData,
  });
  return unwrap(res, path);
}
