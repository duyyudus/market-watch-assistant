import React, { useEffect, useState } from "react";
import {
  Activity,
  Brain,
  ChevronDown,
  ChevronUp,
  Database,
  History,
  Layers,
  Search,
  Sliders,
  Sparkles,
  Timer,
} from "lucide-react";

import { api } from "../../../api";
import type {
  FetchLog,
  ScoreHistory,
  CatalystReview,
  EmbeddingStats,
  LLMCostSummary,
  LLMRun,
  PipelineMetricsRun,
  RetentionJob,
} from "../../../api";
import { Badge } from "../../../components/Badge";
import { EmptyState } from "../../../components/EmptyState";
import { Panel } from "../../../components/Panel";
import { SectionError } from "../../../components/SectionError";
import { SortableHeader } from "../../../components/SortableHeader";
import { useSortableData } from "../../../hooks/useSortableData";

export function EmbeddingsTab() {
  const [stats, setStats] = useState<EmbeddingStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStats = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await api.maintenanceEmbeddingStats();
      setStats(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load embedding stats");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStats();
  }, []);

  if (loading) {
    return (
      <Panel title="Vector Indexing Status">
        <div className="flex py-12 justify-center">
          <span className="loading loading-spinner loading-lg text-indigo-500" />
        </div>
      </Panel>
    );
  }

  if (error || !stats) {
    return (
      <Panel title="Vector Indexing Status">
        <SectionError title="Failed to load stats" message={error || "Empty response"} retry={fetchStats} />
      </Panel>
    );
  }

  return (
    <div className="space-y-6">
      {/* Metrics Row */}
      <div className="grid gap-5 md:grid-cols-2">
        {/* Card 1 */}
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-5 backdrop-blur-sm shadow-md">
          <div className="flex items-center justify-between">
            <span className="text-xs uppercase tracking-wider text-zinc-500 font-bold">News Embedding Coverage</span>
            <Database className="h-4.5 w-4.5 text-indigo-400" />
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-zinc-100">{stats.news_items_with_embeddings}</span>
            <span className="text-zinc-500 text-sm">/ {stats.total_news_items} items</span>
          </div>
          <div className="mt-4">
            <div className="flex items-center justify-between text-xs mb-1">
              <span className="text-zinc-400 font-medium">Coverage Rate</span>
              <span className="font-bold text-indigo-400">{stats.embedding_coverage_pct.toFixed(1)}%</span>
            </div>
            <div className="w-full bg-zinc-800 rounded-full h-2 overflow-hidden border border-zinc-800/80">
              <div
                className="h-2 rounded-full bg-primary"
                style={{ width: `${stats.embedding_coverage_pct}%` }}
              ></div>
            </div>
          </div>
        </div>

        {/* Card 2 */}
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-5 backdrop-blur-sm shadow-md">
          <div className="flex items-center justify-between">
            <span className="text-xs uppercase tracking-wider text-zinc-500 font-bold">Event Embedding Coverage</span>
            <Layers className="h-4.5 w-4.5 text-indigo-400" />
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-zinc-100">{stats.event_clusters_with_embeddings}</span>
            <span className="text-zinc-500 text-sm">/ {stats.total_event_clusters} clusters</span>
          </div>
          <div className="mt-4">
            <div className="flex items-center justify-between text-xs mb-1">
              <span className="text-zinc-400 font-medium">Coverage Rate</span>
              <span className="font-bold text-indigo-400">{stats.cluster_embedding_coverage_pct.toFixed(1)}%</span>
            </div>
            <div className="w-full bg-zinc-800 rounded-full h-2 overflow-hidden border border-zinc-800/80">
              <div
                className="h-2 rounded-full bg-primary"
                style={{ width: `${stats.cluster_embedding_coverage_pct}%` }}
              ></div>
            </div>
          </div>
        </div>
      </div>

      {/* Details Lists */}
      <Panel title="Vector Model Specifications">
        <div className="grid gap-6 md:grid-cols-2">
          {/* News specs */}
          <div className="space-y-4">
            <h4 className="text-xs uppercase tracking-widest text-zinc-400 font-bold border-b border-zinc-800/60 pb-2">
              News Embedding Providers & Models
            </h4>
            <div className="space-y-3">
              <div>
                <span className="text-xs text-zinc-500 block mb-1">Providers</span>
                <div className="flex flex-wrap gap-1.5">
                  {stats.news_providers.length > 0 ? (
                    stats.news_providers.map((p) => (
                      <Badge key={p} tone="neutral">{p}</Badge>
                    ))
                  ) : (
                    <span className="text-sm text-zinc-600 italic">No providers active</span>
                  )}
                </div>
              </div>
              <div>
                <span className="text-xs text-zinc-500 block mb-1">Models</span>
                <div className="flex flex-wrap gap-1.5">
                  {stats.news_models.length > 0 ? (
                    stats.news_models.map((m) => (
                      <Badge key={m} tone="info">{m}</Badge>
                    ))
                  ) : (
                    <span className="text-sm text-zinc-600 italic">No models active</span>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Cluster specs */}
          <div className="space-y-4">
            <h4 className="text-xs uppercase tracking-widest text-zinc-400 font-bold border-b border-zinc-800/60 pb-2">
              Cluster Embedding Providers & Models
            </h4>
            <div className="space-y-3">
              <div>
                <span className="text-xs text-zinc-500 block mb-1">Providers</span>
                <div className="flex flex-wrap gap-1.5">
                  {stats.cluster_providers.length > 0 ? (
                    stats.cluster_providers.map((p) => (
                      <Badge key={p} tone="neutral">{p}</Badge>
                    ))
                  ) : (
                    <span className="text-sm text-zinc-600 italic">No providers active</span>
                  )}
                </div>
              </div>
              <div>
                <span className="text-xs text-zinc-500 block mb-1">Models</span>
                <div className="flex flex-wrap gap-1.5">
                  {stats.cluster_models.length > 0 ? (
                    stats.cluster_models.map((m) => (
                      <Badge key={m} tone="info">{m}</Badge>
                    ))
                  ) : (
                    <span className="text-sm text-zinc-600 italic">No models active</span>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      </Panel>
    </div>
  );
}

/* ==========================================
   TAB 5: LLM DIAGNOSTICS & USAGE RUNS
   ========================================== */
