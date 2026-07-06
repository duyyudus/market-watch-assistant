import {
  Activity,
  Brain,
  DollarSign,
  History,
  Layers,
  LineChart,
  Sliders,
  Sparkles,
  Timer,
  Trash,
} from "lucide-react";
import { useState } from "react";

import type { JobRun } from "../../api";
import { FeatureTabs } from "../../components/FeatureTabs";
import type { ResourceErrors } from "../../types/dashboard";
import {
  CatalystsTab,
  EmbeddingsTab,
  FetchLogsTab,
  JobHistoryTab,
  LLMCostsTab,
  LLMRunsTab,
  MarketMovesTab,
  PipelineMetricsTab,
  RetentionTab,
  ScoreHistoryTab,
} from "./tabs/MaintenanceTabs";

type Tab =
  | "fetch-logs"
  | "job-history"
  | "score-history"
  | "catalysts"
  | "market-moves"
  | "embeddings"
  | "llm-costs"
  | "pipeline-metrics"
  | "llm-runs"
  | "retention";

const MAINTENANCE_TABS = [
  { id: "fetch-logs", label: "Fetch Logs", icon: Activity },
  { id: "job-history", label: "Job History", icon: History },
  { id: "score-history", label: "Score History", icon: Sliders },
  { id: "catalysts", label: "Catalysts", icon: Sparkles },
  { id: "market-moves", label: "Market Moves", icon: LineChart },
  { id: "embeddings", label: "Embeddings Coverage", icon: Layers },
  { id: "llm-runs", label: "LLM Diagnostics", icon: Brain },
  { id: "llm-costs", label: "LLM Costs", icon: DollarSign },
  { id: "pipeline-metrics", label: "Pipeline Metrics", icon: Timer },
  { id: "retention", label: "Retention Logs", icon: Trash },
] satisfies Array<{ id: Tab; label: string; icon: typeof Activity }>;

export function Maintenance({
  jobs,
  errors,
  retry,
}: {
  jobs: JobRun[];
  errors: ResourceErrors;
  retry: () => Promise<void>;
}) {
  const [activeTab, setActiveTab] = useState<Tab>("fetch-logs");

  return (
    <div className="space-y-6">
      <FeatureTabs activeTab={activeTab} onChange={setActiveTab} tabs={MAINTENANCE_TABS} />

      <div className="transition-all duration-300">
        {activeTab === "fetch-logs" && <FetchLogsTab />}
        {activeTab === "job-history" && (
          <JobHistoryTab rows={jobs} error={errors.jobs} retry={retry} />
        )}
        {activeTab === "score-history" && <ScoreHistoryTab />}
        {activeTab === "catalysts" && <CatalystsTab />}
        {activeTab === "market-moves" && <MarketMovesTab />}
        {activeTab === "embeddings" && <EmbeddingsTab />}
        {activeTab === "llm-runs" && <LLMRunsTab />}
        {activeTab === "llm-costs" && <LLMCostsTab />}
        {activeTab === "pipeline-metrics" && <PipelineMetricsTab />}
        {activeTab === "retention" && <RetentionTab />}
      </div>
    </div>
  );
}
