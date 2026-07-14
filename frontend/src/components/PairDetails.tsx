// Панель деталей пари: з'являється справа ТІЛЬКИ після відкриття
// конкретної пари (план, Фаза 1, п.10). Повний Order Book — Фаза 4;
// в MVP показуємо top-of-book обох напрямків.

import type { SpreadRow } from "../types/spread";
import { formatAge, formatPct, trimZeros } from "../utils/format";

interface Props {
  symbol: string;
  rows: SpreadRow[]; // всі напрямки цього символу
  onClose: () => void;
}

export function PairDetails({ symbol, rows, onClose }: Props) {
  return (
    <aside className="details">
      <div className="details-header">
        <h2>{symbol}</h2>
        <button className="btn" onClick={onClose}>
          ✕
        </button>
      </div>
      {rows.map((row) => (
        <div
          key={`${row.buy_exchange}-${row.sell_exchange}`}
          className={`direction ${row.stale ? "stale" : ""}`}
        >
          <div className="direction-title">
            {row.buy_exchange} → {row.sell_exchange}
            {row.stale && <span className="badge badge-stale">STALE</span>}
          </div>
          <dl>
            <dt>Buy ask</dt>
            <dd>{trimZeros(row.buy_price)}</dd>
            <dt>Sell bid</dt>
            <dd>{trimZeros(row.sell_price)}</dd>
            <dt>Gross / Net</dt>
            <dd>
              {formatPct(row.gross_spread_pct)} / <b>{formatPct(row.net_spread_pct)}</b>
            </dd>
            <dt>Обсяг (top)</dt>
            <dd>{trimZeros(row.executable_quantity)}</dd>
            <dt>Notional</dt>
            <dd>{Number(row.executable_notional).toFixed(2)} USDT</dd>
            <dt>Очік. прибуток</dt>
            <dd>{Number(row.expected_net_profit).toFixed(4)} USDT</dd>
            <dt>Вік / Δt</dt>
            <dd>
              {formatAge(row.quote_age_ms)} / {formatAge(row.timestamp_diff_ms)}
            </dd>
          </dl>
        </div>
      ))}
      <p className="muted small">Повний Order Book буде додано у Фазі 4 (VWAP, slippage).</p>
    </aside>
  );
}
