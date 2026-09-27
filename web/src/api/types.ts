// Envelope and payload types come from the backend's JSON Schemas
// (types.gen.ts, `npm run types`); the few plain-JSON endpoints are typed here.
export type {
  AgentEvent,
  ChangeExplanation,
  ChartSpec,
  CitationRef,
  Clarification,
  Contribution,
  CourtComparison,
  CourtRow,
  Decline,
  DocketCard,
  Driver,
  FigureRef,
  JudgeshipContext,
  OfficialFigure,
  OfficialSeries,
  Period,
  Provenance,
  ReconciliationBadge,
  ResultChangeExplanation,
  ResultCourtComparison,
  ResultJudgeshipContext,
  ResultOfficialFigure,
  ResultOfficialSeries,
  RevisionNote,
  SeriesPoint,
  Threshold,
  TurnEnd,
  Usage,
  Warning,
} from "./types.gen";

import type { Clarification, Decline, Provenance, Warning } from "./types.gen";

/** What every core entry point returns (the generated per-type envelopes share it). */
export interface Envelope<T> {
  status: "ok" | "needs_clarification" | "declined";
  data?: T | null;
  clarification?: Clarification | null;
  declined?: Decline | null;
  provenance?: Provenance[];
  warnings?: Warning[];
  suggested_next?: string[];
}

export interface Court {
  code: string;
  name: string;
  citation: string | null;
  level: "national" | "circuit" | "district";
  circuit: string | null;
  state: string | null;
}

export interface Revision {
  measure: string;
  court: string;
  fiscal_year: number;
  first_edition: string;
  first_value: number;
  latest_edition: string;
  latest_value: number;
  delta: number;
  editions: string[];
}

export interface EvalRunSummary {
  run_id: string;
  answerer: string | null;
  label: string | null;
  finished_at: string | null;
  n: number | null;
  correct: number | null;
  accuracy: number | null;
}

export interface EvalItem {
  question_id: string;
  question: string | null;
  suite: string;
  split: "dev" | "test";
  correct: boolean;
  error_category: string | null;
  latency_s: number | null;
  tools_called: string[];
}

export interface EvalRun {
  summary: {
    run_id: string;
    answerer: string;
    label?: string;
    finished_at?: string;
    summary: {
      n: number;
      correct: number;
      accuracy: number;
      by_suite?: Record<string, { n: number; correct: number; accuracy: number }>;
      by_split?: Record<string, { n: number; correct: number; accuracy: number }>;
      [k: string]: unknown;
    };
  };
  items: EvalItem[];
}

export interface GlossaryTerm {
  term: string;
  aliases: string[];
  definition: string;
  source?: string | null;
  related?: string[];
  see_also?: string | null;
}

export interface MethodologyTopic {
  topic: string;
  title: string;
}

/** A structured API error (`{error, message, suggested_next}`). */
export interface ApiErrorBody {
  error: string;
  message?: string;
  suggested_next?: string[];
  details?: unknown;
}
