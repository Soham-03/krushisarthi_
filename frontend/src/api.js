let getToken = null;
export const setTokenGetter = (fn) => { getToken = fn; };

async function authHeaders(extra = {}) {
  const h = { ...extra };
  if (getToken) {
    try { const t = await getToken(); if (t) h.Authorization = "Bearer " + t; } catch { /* signed out */ }
  }
  return h;
}

async function handle(res) {
  if (!res.ok) {
    let msg = res.statusText || "Something went wrong";
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : (j.detail && j.detail[0] && j.detail[0].msg) || msg;
    } catch { /* not json */ }
    const e = new Error(msg); e.status = res.status; throw e;
  }
  return res.json();
}

const json = async (method, path, body) =>
  handle(await fetch(path, { method, headers: await authHeaders(body ? { "Content-Type": "application/json" } : {}), body: body ? JSON.stringify(body) : undefined }));

export const api = {
  get: (p) => json("GET", p),
  post: (p, b) => json("POST", p, b || {}),
  put: (p, b) => json("PUT", p, b),
  patch: (p, b) => json("PATCH", p, b),
  del: (p) => json("DELETE", p),
  upload: async (p, formData) => handle(await fetch(p, { method: "POST", headers: await authHeaders(), body: formData })),
};

const photoCache = new Map();
export async function photoUrl(kind, id) {
  const key = kind + ":" + id;
  if (photoCache.has(key)) return photoCache.get(key);
  const res = await fetch(`/api/photo/${kind}/${id}`, { headers: await authHeaders() });
  if (!res.ok) throw new Error("photo");
  const url = URL.createObjectURL(await res.blob());
  photoCache.set(key, url);
  return url;
}
export const dropPhotoCache = (kind, id) => { photoCache.delete(kind + ":" + id); };
