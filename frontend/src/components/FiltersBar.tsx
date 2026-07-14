export interface Filters {
  exchange: string; // "" = всі
  symbol: string; // "" = всі
  minNetSpreadPct: string; // текстове поле, "" = без фільтра
  minNotional: string;
  onlyValid: boolean;
}

export const EMPTY_FILTERS: Filters = {
  exchange: "",
  symbol: "",
  minNetSpreadPct: "",
  minNotional: "",
  onlyValid: false,
};

interface Props {
  filters: Filters;
  exchanges: string[];
  symbols: string[];
  onChange: (filters: Filters) => void;
}

export function FiltersBar({ filters, exchanges, symbols, onChange }: Props) {
  const set = (patch: Partial<Filters>) => onChange({ ...filters, ...patch });
  return (
    <div className="filters">
      <label>
        Біржа
        <select value={filters.exchange} onChange={(e) => set({ exchange: e.target.value })}>
          <option value="">всі</option>
          {exchanges.map((x) => (
            <option key={x} value={x}>
              {x}
            </option>
          ))}
        </select>
      </label>
      <label>
        Пара
        <select value={filters.symbol} onChange={(e) => set({ symbol: e.target.value })}>
          <option value="">всі</option>
          {symbols.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </label>
      <label>
        Min net spread, %
        <input
          type="number"
          step="0.01"
          placeholder="напр. 0.05"
          value={filters.minNetSpreadPct}
          onChange={(e) => set({ minNetSpreadPct: e.target.value })}
        />
      </label>
      <label>
        Min обсяг, USDT
        <input
          type="number"
          step="1"
          placeholder="напр. 100"
          value={filters.minNotional}
          onChange={(e) => set({ minNotional: e.target.value })}
        />
      </label>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={filters.onlyValid}
          onChange={(e) => set({ onlyValid: e.target.checked })}
        />
        тільки валідні
      </label>
    </div>
  );
}
