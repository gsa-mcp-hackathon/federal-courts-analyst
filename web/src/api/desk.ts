// The request desk (ADR 0013): the three options under an answer, My
// requests, the library, and the simulated statistics office's staff side.
// Sandbox: demo accounts only, and nothing is sent to the AO or the FJC.
import { ApiError, getJson, query } from "./client";
import type { ApiErrorBody } from "./types";
import type {
  CitationRef,
  ResultAuditLog,
  ResultDeskOutcome,
  ResultEligibility,
  ResultInquiryQueue,
  ResultLibraryResults,
  ResultRequestList,
  ResultRequestView,
} from "./types.gen";

export type DeskOption = "ask_office" | "verified_copy" | "notify";

export const OPTION_LABELS: Record<DeskOption, string> = {
  ask_office: "Ask the statistics office why this changed",
  verified_copy: "Save a verified copy",
  notify: "Notify me if these numbers change",
};

export interface DeskAccount {
  id: string;
  name: string;
  role: string;
  role_label: string;
}

export interface CitationIn {
  measure: string;
  court: string;
  fiscal_year: number;
  edition: string;
  value: number;
}

const ACCOUNT_STORAGE = "fca-desk-account";
const STAFF_SESSION = "fca-desk-office";

function read(storage: () => Storage, key: string): string | null {
  try {
    return storage().getItem(key);
  } catch {
    return null;
  }
}

function write(storage: () => Storage, key: string, value: string | null) {
  try {
    if (value === null) storage().removeItem(key);
    else storage().setItem(key, value);
  } catch {
    // Blocked storage: the choice lasts for this page only.
  }
}

export const deskAccount = {
  get: () => read(() => localStorage, ACCOUNT_STORAGE),
  set: (id: string | null) => write(() => localStorage, ACCOUNT_STORAGE, id),
};

export const staffToken = {
  get: () => read(() => sessionStorage, STAFF_SESSION),
  set: (t: string | null) => write(() => sessionStorage, STAFF_SESSION, t),
};

async function send<T>(
  path: string,
  init: { method?: string; body?: unknown; headers?: Record<string, string> },
): Promise<T> {
  const res = await fetch(path, {
    method: init.method ?? "GET",
    headers: {
      accept: "application/json",
      ...(init.body !== undefined ? { "content-type": "application/json" } : {}),
      ...init.headers,
    },
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
  });
  const body: unknown = await res.json().catch(() => ({ error: "bad_response" }));
  if (!res.ok) throw new ApiError(res.status, body as ApiErrorBody);
  return body as T;
}

const asAccount = (): Record<string, string> => {
  const id = deskAccount.get();
  return id ? { "x-desk-account": id } : {};
};
const asStaff = (): Record<string, string> => {
  const t = staffToken.get();
  return t ? { "x-desk-staff-token": t } : {};
};

/** The citations an answer quotes: each figure, plus its first-published
 * value when it was revised (the answer may quote both; the gate keeps only
 * what the text uses). */
export function citationsFrom(refs: CitationRef[]): CitationIn[] {
  const out = new Map<string, CitationIn>();
  for (const r of refs) {
    const add = (edition: string, value: number) =>
      out.set(`${r.measure}|${r.court}|${r.fiscal_year}|${edition}`, {
        measure: r.measure,
        court: r.court,
        fiscal_year: r.fiscal_year,
        edition,
        value,
      });
    add(r.edition, r.value);
    if (r.revised && r.first_published_edition && r.first_published_value != null) {
      add(r.first_published_edition, r.first_published_value);
    }
  }
  return [...out.values()];
}

export const desk = {
  accounts: () =>
    getJson<{ accounts: DeskAccount[]; staff_enabled: boolean }>("/api/desk/accounts"),
  eligibility: (p: { measure: string; court: string; fiscal_year: number }) =>
    getJson<ResultEligibility>(`/api/desk/eligibility${query(p)}`),
  submit: (body: {
    option: DeskOption;
    question: string;
    answer_text: string;
    citations: CitationIn[];
    inquiry?: { measure: string; court: string; fiscal_year: number } | null;
    tool_calls?: { tool: string; arguments: Record<string, unknown> }[];
    idempotency_key?: string;
  }) =>
    send<ResultDeskOutcome>("/api/desk/requests", {
      method: "POST",
      body,
      headers: asAccount(),
    }),
  mine: () => send<ResultRequestList>("/api/desk/requests", { headers: asAccount() }),
  markRead: (id: number) =>
    send<ResultRequestView>(`/api/desk/requests/${id}/read`, {
      method: "POST",
      headers: asAccount(),
    }),
  library: (p: { q?: string; measure?: string; court?: string; fiscal_year?: number }) =>
    getJson<ResultLibraryResults>(`/api/desk/library${query({ ...p, limit: 10 })}`),
  staff: {
    inquiries: () => send<ResultInquiryQueue>("/api/desk/staff/inquiries", { headers: asStaff() }),
    requests: (status?: string) =>
      send<ResultRequestList>(`/api/desk/staff/requests${query({ status })}`, {
        headers: asStaff(),
      }),
    respond: (inquiryId: number, outcome: "confirmed" | "corrected", text: string) =>
      send<ResultDeskOutcome>(`/api/desk/staff/inquiries/${inquiryId}/response`, {
        method: "POST",
        body: { outcome, text },
        headers: asStaff(),
      }),
    publish: (requestId: number) =>
      send<ResultDeskOutcome>(`/api/desk/staff/requests/${requestId}/publish`, {
        method: "POST",
        headers: asStaff(),
      }),
    audit: () => send<ResultAuditLog>("/api/desk/staff/audit", { headers: asStaff() }),
    checkStaleness: () =>
      send<{
        data: {
          citations_checked: number;
          library_entries_flagged: number;
          updates_created: number;
        };
      }>("/api/desk/staff/check-staleness", { method: "POST", headers: asStaff() }),
  },
};
