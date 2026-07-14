// Формат повідомлень backend WS (див. app/spread/engine.py:SpreadRow.to_wire).
// Усі Decimal передаються рядками — конвертація в number тільки для
// відображення/сортування, ніколи для фінансових розрахунків.

export interface SpreadRow {
  symbol: string;
  market_type: string;
  buy_exchange: string;
  sell_exchange: string;
  buy_price: string;
  sell_price: string;
  gross_spread_pct: string;
  net_spread_pct: string;
  executable_quantity: string;
  executable_notional: string;
  expected_net_profit: string;
  quote_age_ms: number;
  timestamp_diff_ms: number;
  stale: boolean;
  valid: boolean;
  calculation_version: number;
}

export interface SpreadUpdateMessage {
  type: "spread_update";
  sequence: number;
  generated_at: number;
  data: SpreadRow[];
}

export interface HeartbeatMessage {
  type: "heartbeat";
  sequence: number;
  generated_at: number;
}

export type WsMessage = SpreadUpdateMessage | HeartbeatMessage;

export type FeedStatus = "connected" | "reconnecting" | "offline";
