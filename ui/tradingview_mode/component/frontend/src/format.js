// Display formatting only. All times are UTC epoch seconds from Python.

export function formatUtc(epochSeconds, withTime = true) {
  if (epochSeconds === null || epochSeconds === undefined) return "—";
  const iso = new Date(epochSeconds * 1000).toISOString();
  return withTime ? `${iso.slice(0, 10)} ${iso.slice(11, 16)}` : iso.slice(0, 10);
}

export function formatPrice(value, precision = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return Number(value).toLocaleString("en-US", { minimumFractionDigits: precision, maximumFractionDigits: precision });
}

export function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return Number(value).toLocaleString("en-US", { maximumFractionDigits: digits });
}

export function formatVolume(value) {
  if (value === null || value === undefined) return "—";
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${(value / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(value / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${(value / 1e3).toFixed(2)}K`;
  return formatNumber(value, 2);
}

export function formatSigned(value, digits = 2, suffix = "") {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value >= 0 ? "+" : ""}${Number(value).toFixed(digits)}${suffix}`;
}

// Compact labels for timeframe buttons; values stay the canonical Python labels.
export function timeframeLabel(value) {
  if (value === "1d") return "D";
  if (value === "1w") return "W";
  return value;
}

export function providerShort(provider) {
  return (provider || "").split(/[\s(]/)[0];
}

export function paramsLabel(params) {
  const values = Object.values(params || {});
  return values.length ? values.join(", ") : "";
}

// Python sends infinities as "inf"/"-inf" (e.g. a loss-free profit factor).
export function formatMetric(value, digits = 2, suffix = "") {
  if (value === "inf") return "∞";
  if (value === "-inf") return "−∞";
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${Number(value).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}${suffix}`;
}

export function formatMoney(value, digits = 2) {
  if (value === null || value === undefined) return "—";
  const sign = value < 0 ? "−" : "";
  return `${sign}$${Math.abs(value).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

export function signClass(value) {
  if (typeof value !== "number" || value === 0) return "";
  return value > 0 ? "up" : "down";
}
