import type { DashboardState, ResourceErrors } from "../types/dashboard";

export const emptyState: DashboardState = {
  status: null,
  sources: [],
  sourceHealth: [],
  events: [],
  eventDetails: {},
  news: [],
  alerts: [],
  alertDetails: {},
  alertChannels: [],
  alertSuppressionRules: [],
  jobs: [],
  watchlist: [],
  commands: [],
  alertPolicy: null,
  presets: null,
};

export const emptyErrors: ResourceErrors = {};
