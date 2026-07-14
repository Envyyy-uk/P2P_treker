// WS-клієнт: reconnect з backoff, контроль sequence (виявлення пропусків),
// пауза UI без розриву з'єднання (backend продовжує працювати).

import { useCallback, useEffect, useRef, useState } from "react";
import type { FeedStatus, SpreadRow, WsMessage } from "../types/spread";

const WS_PATH = "/ws/spreads";
const MAX_BACKOFF_MS = 15000;

function wsUrl(): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}${WS_PATH}`;
}

export interface SpreadFeed {
  rows: SpreadRow[];
  status: FeedStatus;
  lastUpdate: number | null;
  missedMessages: number;
  paused: boolean;
  togglePause: () => void;
}

export function useSpreadFeed(): SpreadFeed {
  const [rows, setRows] = useState<SpreadRow[]>([]);
  const [status, setStatus] = useState<FeedStatus>("offline");
  const [lastUpdate, setLastUpdate] = useState<number | null>(null);
  const [missedMessages, setMissedMessages] = useState(0);
  const [paused, setPaused] = useState(false);

  const pausedRef = useRef(paused);
  pausedRef.current = paused;
  const lastSeqRef = useRef<number | null>(null);
  const backoffRef = useRef(1000);

  const togglePause = useCallback(() => setPaused((p) => !p), []);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let retryTimer: number | undefined;

    const connect = () => {
      setStatus((s) => (s === "connected" ? s : "reconnecting"));
      ws = new WebSocket(wsUrl());

      ws.onopen = () => {
        backoffRef.current = 1000;
        lastSeqRef.current = null; // новий потік sequence після reconnect
        setStatus("connected");
      };

      ws.onmessage = (event) => {
        const message = JSON.parse(event.data) as WsMessage;
        if (lastSeqRef.current !== null && message.sequence > lastSeqRef.current + 1) {
          setMissedMessages((m) => m + (message.sequence - lastSeqRef.current! - 1));
        }
        lastSeqRef.current = message.sequence;
        if (message.type === "spread_update" && !pausedRef.current) {
          setRows(message.data);
          setLastUpdate(message.generated_at);
        }
      };

      ws.onclose = () => {
        if (closed) return;
        setStatus("reconnecting");
        retryTimer = window.setTimeout(connect, backoffRef.current);
        backoffRef.current = Math.min(backoffRef.current * 2, MAX_BACKOFF_MS);
      };

      ws.onerror = () => ws?.close();
    };

    connect();
    return () => {
      closed = true;
      window.clearTimeout(retryTimer);
      ws?.close();
      setStatus("offline");
    };
  }, []);

  return { rows, status, lastUpdate, missedMessages, paused, togglePause };
}
