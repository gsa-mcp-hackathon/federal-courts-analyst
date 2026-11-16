// The API requests the mocked e2e journeys make (and fixture keys for them).
export const keyOf = (url) => {
  const u = new URL(url, "http://x");
  const q = [...u.searchParams.entries()].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  return u.pathname + (q.length ? "?" + new URLSearchParams(q).toString() : "");
};

const TRENDS = [
  "weighted_total_filings_per_judgeship",
  "civil_cases_filed",
  "civil_cases_pending",
  "civil_median_months_to_disposition",
];

export const URLS = [
  "/api/courts",
  "/api/compare?measure=weighted_total_filings_per_judgeship&fiscal_year=2025&edition=latest",
  "/api/compare?measure=weighted_total_filings_per_judgeship&fiscal_year=2024&edition=latest",
  "/api/compare?measure=weighted_total_filings_per_judgeship&fiscal_year=2025&edition=first_published",
  "/api/courts/FL-N/profile?fiscal_year=2025",
  ...TRENDS.map((m) => `/api/figures/${m}/FL-N/series?from=2016&to=2025`),
  "/api/courts/FL-N/case-mix?fiscal_year=2025",
  "/api/courts/FL-N/reconcile?fiscal_year=2025&measure=civil_cases_filed",
  "/api/revisions?court=FL-N",
  "/api/figures?measure=weighted_civil_filings_per_judgeship&court=US&fiscal_year=2020",
  "/api/figures/weighted_civil_filings_per_judgeship/US/editions",
  "/api/figures/weighted_civil_filings_per_judgeship/US/series?from=2016&to=2025&edition=first_published",
  "/api/revisions?measure=weighted_civil_filings_per_judgeship&court=US",
  "/api/eval/runs",
  "/api/eval/runs/phase7-adversarial-agent-r2",
  "/api/methodology",
  "/api/methodology/weighted-filings",
  "/api/glossary",
];
