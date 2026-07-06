import { Activity } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../../../api";
import type { MarketMove } from "../../../api";
import { Badge } from "../../../components/Badge";
import { EmptyState } from "../../../components/EmptyState";
import { Panel } from "../../../components/Panel";
import { SectionError } from "../../../components/SectionError";

const DEFAULT_LIMIT = 100;
const MIN_LIMIT = 1;
const MAX_LIMIT = 200;

function clampLimit(value: number) {
  return Math.min(MAX_LIMIT, Math.max(MIN_LIMIT, Math.trunc(value)));
}

function formatTime(value: string) {
  return new Date(value).toLocaleString();
}

function formatPercent(value?: number | null, digits = 2) {
  if (value == null) return "-";
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

function formatNumber(value?: number | null, digits = 2) {
  if (value == null) return "-";
  return value.toFixed(digits);
}

export function MarketMovesTab() {
  const [moves, setMoves] = useState<MarketMove[]>([]);
  const [limit, setLimit] = useState(DEFAULT_LIMIT);
  const [limitInput, setLimitInput] = useState(String(DEFAULT_LIMIT));
  const [reloadKey, setReloadKey] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const commitLimitInput = () => {
    const trimmed = limitInput.trim();
    if (!trimmed) {
      setLimitInput(String(limit));
      return;
    }
    const next = Number(trimmed);
    if (!Number.isFinite(next)) {
      setLimitInput(String(limit));
      return;
    }
    const clamped = clampLimit(next);
    setLimit(clamped);
    setLimitInput(String(clamped));
  };

  const retry = async () => {
    setReloadKey((value) => value + 1);
  };

  useEffect(() => {
    let cancelled = false;

    async function fetchMarketMoves() {
      try {
        setLoading(true);
        setError(null);
        const response = await api.marketMoves(limit);
        if (!cancelled) {
          setMoves(response.items);
        }
      } catch (err: unknown) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load market moves");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    fetchMarketMoves();

    return () => {
      cancelled = true;
    };
  }, [limit, reloadKey]);

  return (
    <Panel title="Market Moves">
      {error ? (
        <SectionError
          title="Failed to load market moves"
          message={error}
          retry={retry}
        />
      ) : (
        <div className="space-y-4">
          <div className="flex flex-col gap-3 rounded-lg border border-zinc-800/40 bg-zinc-950/20 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="text-sm text-zinc-400">
              Showing the most recent stored market move snapshots.
            </div>
            <label className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-zinc-500">
              Limit
              <input
                className="input input-sm input-bordered w-24 border-zinc-800 bg-zinc-950/40 text-zinc-200"
                max={MAX_LIMIT}
                min={MIN_LIMIT}
                onChange={(event) => {
                  setLimitInput(event.target.value);
                }}
                onBlur={commitLimitInput}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    commitLimitInput();
                  }
                }}
                type="number"
                value={limitInput}
              />
            </label>
          </div>

          {loading ? (
            <div className="flex justify-center py-12">
              <span className="loading loading-spinner loading-lg text-indigo-500" />
            </div>
          ) : moves.length === 0 ? (
            <EmptyState
              icon={Activity}
              title="No market moves"
              body="No market move snapshots have been stored yet."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="table w-full text-zinc-300">
                <thead>
                  <tr className="border-b border-zinc-800/80 bg-zinc-950/40">
                    <th>Captured</th>
                    <th>Symbol</th>
                    <th>Class</th>
                    <th>Exchange</th>
                    <th>Window</th>
                    <th>Price Change</th>
                    <th>Volume Change</th>
                    <th>Value Traded</th>
                    <th>Z-Score</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800/40">
                  {moves.map((move) => {
                    const priceClass =
                      move.price_change_pct >= 0 ? "text-emerald-400" : "text-rose-400";
                    return (
                      <tr className="transition-colors hover:bg-zinc-800/10" key={move.id}>
                        <td className="whitespace-nowrap text-xs text-zinc-400">
                          {formatTime(move.timestamp)}
                        </td>
                        <td className="font-bold text-zinc-100">{move.asset_symbol}</td>
                        <td>
                          <Badge tone="neutral">{move.asset_class}</Badge>
                        </td>
                        <td className="text-sm text-zinc-400">{move.exchange || "-"}</td>
                        <td className="font-semibold text-zinc-300">{move.window}</td>
                        <td className={`font-mono text-sm font-semibold ${priceClass}`}>
                          {formatPercent(move.price_change_pct)}
                        </td>
                        <td className="font-mono text-xs">
                          {formatPercent(move.volume_change_pct, 1)}
                        </td>
                        <td className="font-mono text-xs">
                          {formatPercent(move.value_traded_change_pct, 1)}
                        </td>
                        <td className="font-mono text-xs">{formatNumber(move.z_score)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          <div className="border-t border-zinc-800/40 pt-4 text-xs text-zinc-500">
            Showing <span className="font-semibold text-zinc-300">{moves.length}</span> most
            recent market moves.
          </div>
        </div>
      )}
    </Panel>
  );
}
