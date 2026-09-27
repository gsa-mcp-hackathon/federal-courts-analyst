// The measures the explorer pages offer, with URL slugs and the thresholds
// that apply to them. Labels match the server's measure registry.

export interface MeasureInfo {
  id: string;
  slug: string;
  label: string;
  short: string;
  unit: string;
  /** Judicial Conference thresholds apply (weighted total filings). */
  thresholds: boolean;
}

export const MEASURES: MeasureInfo[] = [
  {
    id: "weighted_total_filings_per_judgeship",
    slug: "weighted-filings-per-judgeship",
    label: "Weighted filings per judgeship",
    short: "Weighted total",
    unit: "weighted filings per judgeship",
    thresholds: true,
  },
  {
    id: "total_filings_per_judgeship",
    slug: "filings-per-judgeship",
    label: "Filings per judgeship (unweighted)",
    short: "Total, unweighted",
    unit: "filings per judgeship",
    thresholds: false,
  },
  {
    id: "weighted_civil_filings_per_judgeship",
    slug: "weighted-civil-filings-per-judgeship",
    label: "Weighted civil filings per judgeship",
    short: "Weighted civil",
    unit: "weighted filings per judgeship",
    thresholds: false,
  },
  {
    id: "civil_filings_per_judgeship",
    slug: "civil-filings-per-judgeship",
    label: "Civil filings per judgeship (unweighted)",
    short: "Civil, unweighted",
    unit: "filings per judgeship",
    thresholds: false,
  },
  {
    id: "civil_cases_filed",
    slug: "civil-cases-filed",
    label: "Civil cases filed",
    short: "Civil filed",
    unit: "cases",
    thresholds: false,
  },
  {
    id: "civil_cases_pending",
    slug: "civil-cases-pending",
    label: "Civil cases pending",
    short: "Civil pending",
    unit: "cases",
    thresholds: false,
  },
  {
    id: "civil_median_months_to_disposition",
    slug: "civil-median-months-to-disposition",
    label: "Median time to disposition, civil (months)",
    short: "Civil median time",
    unit: "months",
    thresholds: false,
  },
];

export const bySlug = (slug: string) => MEASURES.find((m) => m.slug === slug);
export const byId = (id: string) => MEASURES.find((m) => m.id === id);

/** 430: the Conference's standard for considering a judgeship; 600: the
 * judicial-emergency filings threshold (with a vacancy). */
export const THRESHOLDS = [430, 600] as const;

export const FY_MIN = 2016;
export const FY_MAX = 2025;
