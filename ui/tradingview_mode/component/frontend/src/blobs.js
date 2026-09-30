// Rebuild the payload Python validated from its blob markers (see component/blobs.py).
//
// {"$blob": url, "tail": [...]} stands for (the JSON array stored at url) + tail. A URL names its content, so a
// fetched array is kept by URL and never fetched again while it is in use; in Live only the inline tail changes.

const MAX_CACHED = 256;
const cache = new Map();            // url -> Promise<array>

export function isBlob(value) {
  return !!value && typeof value === "object" && !Array.isArray(value) && typeof value.$blob === "string"
    && Object.keys(value).every((k) => k === "$blob" || k === "tail");
}

export function isJson(value) {
  return !!value && typeof value === "object" && !Array.isArray(value) && typeof value.$json === "string"
    && Object.keys(value).length === 1;
}

export function blobUrls(value, out = new Set()) {
  if (isBlob(value)) { out.add(value.$blob); (value.tail || []).forEach((item) => blobUrls(item, out)); }
  else if (isJson(value)) out.add(value.$json);
  else if (Array.isArray(value)) value.forEach((item) => blobUrls(item, out));
  else if (value && typeof value === "object") Object.values(value).forEach((item) => blobUrls(item, out));
  return out;
}

export function rebuild(value, arrays) {
  if (isBlob(value)) return rebuild(arrays.get(value.$blob), arrays).concat((value.tail || []).map((item) => rebuild(item, arrays)));
  if (isJson(value)) return rebuild(arrays.get(value.$json), arrays);
  if (Array.isArray(value)) return value.map((item) => rebuild(item, arrays));
  if (value && typeof value === "object") {
    const out = {};
    for (const [key, item] of Object.entries(value)) out[key] = rebuild(item, arrays);
    return out;
  }
  return value;
}

function fetchBlob(url, fetcher) {
  if (!cache.has(url)) {
    const request = fetcher(url).then((response) => {
      if (!response.ok) throw new Error(`blob ${url}: HTTP ${response.status}`);
      return response.json();
    });
    request.catch(() => cache.delete(url));        // a failed fetch is retried next time
    cache.set(url, request);
    while (cache.size > MAX_CACHED) cache.delete(cache.keys().next().value);
  }
  return cache.get(url);
}

// Resolve every marker; resolves to the full payload (identical to what Python built).
export async function hydrate(payload, fetcher = (url) => fetch(new URL(url, window.location.origin), { credentials: "same-origin" })) {
  // stored values may hold further markers (a large object whose large children were stored first)
  const arrays = new Map();
  let pending = [...blobUrls(payload)];
  while (pending.length) {
    const fetched = await Promise.all(pending.map(async (url) => [url, await fetchBlob(url, fetcher)]));
    fetched.forEach(([url, value]) => arrays.set(url, value));
    pending = [...new Set(fetched.flatMap(([, value]) => [...blobUrls(value)]))].filter((url) => !arrays.has(url));
  }
  if (!arrays.size) return payload;
  const used = new Set(arrays.keys());
  for (const key of [...cache.keys()]) if (!used.has(key) && cache.size > MAX_CACHED / 2) cache.delete(key);
  return rebuild(payload, arrays);
}
