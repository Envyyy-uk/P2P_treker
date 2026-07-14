import type { FeedStatus } from "../types/spread";
import { formatTime } from "../utils/format";

const LABELS: Record<FeedStatus, string> = {
  connected: "Connected",
  reconnecting: "Reconnecting…",
  offline: "Offline",
};

interface Props {
  status: FeedStatus;
  lastUpdate: number | null;
  missedMessages: number;
  paused: boolean;
  onTogglePause: () => void;
}

export function StatusBar({ status, lastUpdate, missedMessages, paused, onTogglePause }: Props) {
  return (
    <header className="status-bar">
      <h1>Spread Monitor MVP</h1>
      <div className="status-group">
        <span className={`status-dot status-${status}`} />
        <span>{LABELS[status]}</span>
        {lastUpdate !== null && <span className="muted">оновлено {formatTime(lastUpdate)}</span>}
        {missedMessages > 0 && (
          <span className="warn" title="Пропущені повідомлення за sequence">
            пропущено: {missedMessages}
          </span>
        )}
        <button onClick={onTogglePause} className={paused ? "btn paused" : "btn"}>
          {paused ? "▶ Продовжити" : "⏸ Пауза UI"}
        </button>
      </div>
    </header>
  );
}
