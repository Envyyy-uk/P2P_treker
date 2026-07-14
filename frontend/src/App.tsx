import { useMemo, useState } from "react";
import { EMPTY_FILTERS, Filters, FiltersBar } from "./components/FiltersBar";
import { PairDetails } from "./components/PairDetails";
import { rowKey, SortDir, SpreadTable } from "./components/SpreadTable";
import { useSpreadFeed } from "./hooks/useSpreadFeed";
import { StatusBar } from "./components/StatusBar";

export default function App() {
  const feed = useSpreadFeed();
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [selected, setSelected] = useState<string | null>(null); // rowKey
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);

  const exchanges = useMemo(
    () => [...new Set(feed.rows.flatMap((r) => [r.buy_exchange, r.sell_exchange]))].sort(),
    [feed.rows],
  );
  const symbols = useMemo(() => [...new Set(feed.rows.map((r) => r.symbol))].sort(), [feed.rows]);

  const visible = useMemo(() => {
    let rows = feed.rows;
    if (filters.exchange) {
      rows = rows.filter(
        (r) => r.buy_exchange === filters.exchange || r.sell_exchange === filters.exchange,
      );
    }
    if (filters.symbol) rows = rows.filter((r) => r.symbol === filters.symbol);
    if (filters.minNetSpreadPct !== "") {
      const min = Number(filters.minNetSpreadPct);
      rows = rows.filter((r) => Number(r.net_spread_pct) >= min);
    }
    if (filters.minNotional !== "") {
      const min = Number(filters.minNotional);
      rows = rows.filter((r) => Number(r.executable_notional) >= min);
    }
    if (filters.onlyValid) rows = rows.filter((r) => r.valid);
    const sign = sortDir === "desc" ? -1 : 1;
    return [...rows].sort(
      (a, b) => sign * (Number(a.net_spread_pct) - Number(b.net_spread_pct)),
    );
  }, [feed.rows, filters, sortDir]);

  const detailRows = useMemo(
    () => (selectedSymbol ? feed.rows.filter((r) => r.symbol === selectedSymbol) : []),
    [feed.rows, selectedSymbol],
  );

  return (
    <div className="app">
      <StatusBar
        status={feed.status}
        lastUpdate={feed.lastUpdate}
        missedMessages={feed.missedMessages}
        paused={feed.paused}
        onTogglePause={feed.togglePause}
      />
      <FiltersBar filters={filters} exchanges={exchanges} symbols={symbols} onChange={setFilters} />
      <main className={selectedSymbol ? "content with-details" : "content"}>
        <SpreadTable
          rows={visible}
          sortDir={sortDir}
          onToggleSort={() => setSortDir((d) => (d === "desc" ? "asc" : "desc"))}
          selectedKey={selected}
          onSelect={(row) => {
            setSelected(rowKey(row));
            setSelectedSymbol(row.symbol);
          }}
        />
        {selectedSymbol && (
          <PairDetails
            symbol={selectedSymbol}
            rows={detailRows}
            onClose={() => {
              setSelectedSymbol(null);
              setSelected(null);
            }}
          />
        )}
      </main>
    </div>
  );
}
