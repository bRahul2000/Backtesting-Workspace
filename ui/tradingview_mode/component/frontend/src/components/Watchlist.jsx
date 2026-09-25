import React from "react";
import { sendEvent } from "../events.js";
import { formatPrice, formatSigned, providerShort, timeframeLabel } from "../format.js";

// A live row: always names its source; no quote means no price (never another source's).
function LiveRow({ item, timeframe }) {
  const status = item.live?.status;
  const label = `${item.source_label} ${status === "LIVE" ? "LIVE" : status === "STALE" ? "STALE" : "OFF"}`;
  return (
    <button type="button" className={`wl-row is-live-row ${item.selected ? "is-active" : ""}`} data-source={item.source}
      title={`${item.title}${item.live ? ` · Bid ${item.live.bid} · Ask ${item.live.ask}` : " · no current quote"}`}
      onClick={() => !item.selected && sendEvent("go_live", { market: item.market, source: item.source, timeframe })}>
      <span className="wl-symbol">{item.symbol}</span>
      <span className="wl-last mono">{item.live ? formatPrice(item.live.bid, item.live.digits ?? item.price_precision) : "—"}</span>
      <span className="wl-sub">
        <span className={`wl-live mono ${status === "LIVE" ? "is-live" : status === "STALE" ? "is-stale" : "is-off"}`}>{label}</span>
        {" · "}{item.title.split(" · ")[0]}
      </span>
    </button>
  );
}

export function Watchlist({ items, replay, live, timeframe }) {
  const liveRows = items.filter((item) => item.kind === "live");
  const datasets = items.filter((item) => item.kind !== "live");
  return (
    <aside className="watchlist" aria-label="Watchlist">
      <div className="panel-head">
        <span>Watchlist</span>
        <span className="muted">{items.length}</span>
      </div>
      <div className="wl-cols"><span>Symbol</span><span>{liveRows.length ? "Bid / Last" : "Last"}</span><span>Chg%</span></div>
      <div className="wl-body">
        {liveRows.length > 0 && <div className="wl-group">Live markets</div>}
        {liveRows.map((item) => <LiveRow key={item.dataset_key} item={item} timeframe={timeframe} />)}
        {liveRows.length > 0 && <div className="wl-group">Historical datasets</div>}
        {datasets.map((item) => {
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
      <div className="wl-foot">
        {replay
          ? <span className="warn-inline">Reference only: latest local close, not replay prices.</span>
          : live
            ? "Live rows: bid from the named source · historical rows: last local close"
            : "Registered local datasets · last native bar"}
      </div>
    </aside>
  );
}
