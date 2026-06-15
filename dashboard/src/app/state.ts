import type { DashboardState, ResourceErrors } from "../types/dashboard";

export const emptyState: DashboardState = {
  status: null,
  sources: [],
  sourceHealth: [],
  events: [],
  eventsTotal: 0,
  eventDetails: {},
  news: [],
  newsTotal: 0,
  newsDomains: [],
  newsFilterOptions: { statuses: [], regions: [] },
  newsDetails: {},
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
