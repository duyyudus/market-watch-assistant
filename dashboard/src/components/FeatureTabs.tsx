import type { LucideIcon } from "lucide-react";

import { classNames } from "../lib/classNames";

export type FeatureTab<T extends string> = {
  id: T;
  label: string;
  icon?: LucideIcon;
};

export function FeatureTabs<T extends string>({
  tabs,
  activeTab,
  onChange,
}: {
  tabs: FeatureTab<T>[];
  activeTab: T;
  onChange: (tab: T) => void;
}) {
  return (
    <div className="tabs tabs-boxed flex flex-wrap gap-1 border border-zinc-800/60 bg-zinc-950/60 p-1">
      {tabs.map((tab) => {
        const Icon = tab.icon;
        return (
          <button
            className={classNames(
              "tab tab-sm flex items-center gap-2",
              activeTab === tab.id ? "tab-active" : "text-zinc-400 hover:text-zinc-200",
            )}
            key={tab.id}
            onClick={() => onChange(tab.id)}
            type="button"
          >
            {Icon ? <Icon className="h-3.5 w-3.5" /> : null}
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
