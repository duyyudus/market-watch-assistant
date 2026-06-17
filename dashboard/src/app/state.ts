import type { DashboardState, ResourceErrors } from "../types/dashboard";

export const emptyState: DashboardState = {
  status: null,
  sources: [],
  sourceHealth: [],
  events: [],
  eventsTotal: 0,
  eventDetails: {},
  overviewSegments: {},
  news: [],
  newsTotal: 0,
  newsDomains: [],
  newsFilterOptions: { statuses: [], regions: [] },
  newsDetails: {},
  alerts: [],
  alertsTotal: 0,
  alertDetails: {},
  alertChannels: [],
  alertSuppressionRules: [],
  jobs: [],
  watchlist: [],
  commands: [],
  catalystReviews: [],
  catalystReviewsTotal: 0,
  latestDigest: null,
  alertPolicy: null,
  presets: null,
};

export const emptyErrors: ResourceErrors = {};
