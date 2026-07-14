import type { SpreadRow } from "../types/spread";
import { formatAge, formatPct, trimZeros } from "../utils/format";

export type SortDir = "desc" | "asc";

interface Props {
  rows: SpreadRow[];
  sortDir: SortDir;
  onToggleSort: () => void;
  selectedKey: string | null;
  onSelect: (row: SpreadRow) => void;
}

export function rowKey(row: SpreadRow): string {
  return `${row.symbol}|${row.buy_exchange}|${row.sell_exchange}`;
}

function netClass(row: SpreadRow): string {
  if (row.stale) return "stale";
  const net = Number(row.net_spread_pct);
  if (net > 0) return "positive";
  if (net < 0) return "negative";
  return "";
}

export function SpreadTable({ rows, sortDir, onToggleSort, selectedKey, onSelect }: Props) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Market</th>
            <th>Buy @</th>
            <th>Sell @</th>
            <th>Buy Ask</th>
            <th>Sell Bid</th>
            <th>Gross</th>
            <th className="sortable" onClick={onToggleSort}>
              Net {sortDir === "desc" ? "▼" : "▲"}
            </th>
            <th>Qty</th>
            <th>Notional</th>
            <th>Profit</th>
            <th>Age</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td colSpan={13} className="empty">
                Немає даних — очікування котирувань…
              </td>
            </tr>
          )}
          {rows.map((row) => {
            const key = rowKey(row);
            return (
              <tr
                key={key}
                className={`${netClass(row)} ${selectedKey === key ? "selected" : ""}`}
                onClick={() => onSelect(row)}
              >
                <td>{row.symbol}</td>
                <td>{row.market_type}</td>
                <td>{row.buy_exchange}</td>
                <td>{row.sell_exchange}</td>
                <td className="num">{trimZeros(row.buy_price)}</td>
                <td className="num">{trimZeros(row.sell_price)}</td>
                <td className="num">{formatPct(row.gross_spread_pct)}</td>
                <td className="num strong">{formatPct(row.net_spread_pct)}</td>
                <td className="num">{trimZeros(row.executable_quantity)}</td>
                <td className="num">{Number(row.executable_notional).toFixed(2)}</td>
                <td className="num">{Number(row.expected_net_profit).toFixed(4)}</td>
                <td className="num">{formatAge(row.quote_age_ms)}</td>
                <td>
                  {row.stale ? (
                    <span className="badge badge-stale">STALE</span>
                  ) : row.valid ? (
                    <span className="badge badge-ok">OK</span>
                  ) : (
                    <span className="badge badge-skip">SKIP</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
