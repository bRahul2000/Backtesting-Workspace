import React from "react";
import { sendEvent } from "../events.js";
import { formatPrice, formatSigned, providerShort, timeframeLabel } from "../format.js";

export function Watchlist({ items }) {
  return (
    <aside className="watchlist" aria-label="Watchlist">
      <div className="panel-head">
        <span>Watchlist</span>
        <span className="muted">{items.length}</span>
      </div>
      <div className="wl-cols"><span>Symbol</span><span>Last</span><span>Chg%</span></div>
      <div className="wl-body">
        {items.map((item) => {
          const direction = item.change_pct === null ? "" : item.change_pct >= 0 ? "up" : "down";
          return (
            <button key={item.dataset_key} type="button" className={`wl-row ${item.selected ? "is-active" : ""}`}
              title={`${item.symbol} · ${item.provider}`}
              onClick={() => !item.selected && sendEvent("select_watchlist_item", { dataset_key: item.dataset_key })}>
              <span className="wl-symbol">{item.symbol}</span>
              <span className="wl-last mono">{formatPrice(item.last_close, item.price_precision)}</span>
              <span className={`wl-chg mono ${direction}`}>{formatSigned(item.change_pct, 2, "%")}</span>
              <span className="wl-sub">{providerShort(item.provider)} · {item.native_timeframes.map(timeframeLabel).join(" ")}</span>
            </button>
          );
        })}
      </div>
      <div className="wl-foot">Registered local datasets · last native bar</div>
    </aside>
  );
}
