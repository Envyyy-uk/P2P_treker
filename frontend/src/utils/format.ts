export function formatPct(value: string): string {
  const n = Number(value);
  return `${n >= 0 ? "+" : ""}${n.toFixed(4)}%`;
}

export function formatAge(ms: number): string {
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

export function formatTime(tsMs: number): string {
  return new Date(tsMs).toLocaleTimeString("uk-UA", { hour12: false });
}

export function trimZeros(value: string): string {
  if (!value.includes(".")) return value;
  return value.replace(/\.?0+$/, "");
}
