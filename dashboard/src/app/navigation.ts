import {
  Activity,
  Bell,
  Database,
  Newspaper,
  Radio,
  Settings,
  Star,
  TerminalSquare,
  Wrench,
  type LucideIcon,
} from "lucide-react";

import type { View } from "../types/dashboard";

export const nav: { id: View; label: string; icon: LucideIcon }[] = [
  { id: "overview", label: "Overview", icon: Activity },
  { id: "events", label: "Events", icon: Database },
  { id: "news", label: "News", icon: Newspaper },
  { id: "alerts", label: "Alerts", icon: Bell },
  { id: "sources", label: "Sources", icon: Radio },
  { id: "watchlist", label: "Watchlist", icon: Star },
  { id: "commands", label: "Commands", icon: TerminalSquare },
  { id: "operations", label: "Operations", icon: Settings },
  { id: "maintenance", label: "Maintenance", icon: Wrench },
];


