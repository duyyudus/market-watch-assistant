import type { DashboardState, ResourceErrors } from "../types/dashboard";

export const emptyState: DashboardState = {
  status: null,
  sources: [],
  events: [],
  news: [],
  alerts: [],
  jobs: [],
  watchlist: [],
  commands: [],
  alertPolicy: null,
  presets: null,
};

export const emptyErrors: ResourceErrors = {};
