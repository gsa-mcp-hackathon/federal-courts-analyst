import type {
  ApiErrorBody,
  Court,
  Envelope,
  EvalRun,
  EvalRunSummary,
  GlossaryTerm,
  JudgeshipContext,
  MethodologyTopic,
  OfficialFigure,
  OfficialSeries,
  ChangeExplanation,
  CourtComparison,
  Revision,
} from "./types";
import type { CohortAnalysis, EditionVintages, Reconciliation } from "./types.gen";

export class ApiError extends Error {
  readonly status: number;
  readonly body: ApiErrorBody;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message ?? body.error ?? `HTTP ${status}`);
    this.status = status;
    this.body = body;
  }
}

type Params = Record<string, string | number | boolean | string[] | null | undefined>;

export function query(params: Params): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => q.append(k, x));
    else q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(path, { headers: { accept: "application/json" }, signal });
  const body: unknown = await res.json().catch(() => ({ error: "bad_response" }));
  if (!res.ok) throw new ApiError(res.status, body as ApiErrorBody);
  return body as T;
}

export const api = {
  figure: (p: { measure: string; fiscal_year: number; court?: string; edition?: string }) =>
    getJson<Envelope<OfficialFigure>>(`/api/figures${query(p)}`),
  series: (
    measure: string,
    court: string,
    from: number,
    to: number,
    allowMixed = false,
    edition?: string,
  ) =>
    getJson<Envelope<OfficialSeries>>(
      `/api/figures/${encodeURIComponent(measure)}/${encodeURIComponent(court)}/series${query({
        from,
        to,
        edition,
        allow_mixed: allowMixed || undefined,
      })}`,
    ),
  vintages: (measure: string, court: string) =>
    getJson<Envelope<EditionVintages>>(
      `/api/figures/${encodeURIComponent(measure)}/${encodeURIComponent(court)}/editions`,
    ),
  caseMix: (court: string, fiscal_year: number) =>
    getJson<Envelope<CohortAnalysis>>(
      `/api/courts/${encodeURIComponent(court)}/case-mix${query({ fiscal_year })}`,
    ),
  reconcile: (court: string, fiscal_year: number, measure = "civil_cases_filed") =>
    getJson<Envelope<Reconciliation>>(
      `/api/courts/${encodeURIComponent(court)}/reconcile${query({ fiscal_year, measure })}`,
    ),
  compare: (p: {
    measure: string;
    fiscal_year: number;
    edition?: string;
    courts?: string[];
    top_n?: number;
    order?: "asc" | "desc";
  }) => getJson<Envelope<CourtComparison>>(`/api/compare${query(p)}`),
  explain: (p: { measure: string; court: string; from: number; to: number }) =>
    getJson<Envelope<ChangeExplanation>>(`/api/explain-change${query(p)}`),
  courts: () => getJson<{ courts: Court[] }>("/api/courts"),
  profile: (court: string, fiscal_year?: number) =>
    getJson<Envelope<JudgeshipContext>>(
      `/api/courts/${encodeURIComponent(court)}/profile${query({ fiscal_year })}`,
    ),
  revisions: (p: { measure?: string; court?: string }) =>
    getJson<{ revisions: Revision[] }>(`/api/revisions${query(p)}`),
  evalRuns: () => getJson<{ runs: EvalRunSummary[] }>("/api/eval/runs"),
  evalRun: (id: string) => getJson<EvalRun>(`/api/eval/runs/${encodeURIComponent(id)}`),
  glossary: () => getJson<{ terms: GlossaryTerm[] }>("/api/glossary"),
  methodology: () => getJson<{ topics: MethodologyTopic[] }>("/api/methodology"),
  methodologyTopic: (topic: string) =>
    getJson<{ topic: string; markdown: string }>(`/api/methodology/${encodeURIComponent(topic)}`),
};
