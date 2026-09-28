// P3.1 Pine strategy fills -> chart markers. Presentation only: every fill (bar time, side, quantity, price, kind) is
// computed by Python's broker emulator; nothing here simulates or decides a trade.

const LABELS = { trail: "Trail", stop: "SL", limit: "TP", close: "Close", reversal: "Rev", margin_call: "Margin" };

export function strategyMarkers(fills, colors = { buy: "#2962ff", sell: "#e91e63" }) {
  const markers = [];
  for (const fill of fills || []) {
    if (fill.time === null || fill.time === undefined) continue;
    const buy = fill.side > 0;
    const qty = Number.isInteger(fill.qty) || Math.abs(fill.qty - Math.round(fill.qty)) < 1e-9
      ? String(Math.round(fill.qty)) : String(Number(fill.qty.toFixed(6)));
    const label = fill.kind === "exit" || fill.kind === "close" ? LABELS[fill.exit_kind] : null;
    const tag = label && label.toLowerCase() !== String(fill.id).toLowerCase() ? `${fill.id} ${label}` : fill.id;
    markers.push({
      time: fill.time, position: buy ? "belowBar" : "aboveBar", shape: buy ? "arrowUp" : "arrowDown",
      color: buy ? colors.buy : colors.sell, text: `${tag} ${buy ? "+" : "-"}${qty}`, id: fill.key,
    });
  }
  markers.sort((a, b) => a.time - b.time);
  return markers;
}
