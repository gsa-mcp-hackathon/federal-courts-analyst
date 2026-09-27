import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { api } from "@/api/client";
import type { EvalRunSummary } from "@/api/types";
import { PageHeader } from "@/components/Layout";
import { Icon } from "@/components/Icon";
import { EmptyState, ErrorState, Loading } from "@/components/States";
import { fmtPct } from "@/lib/format";

/** The runs each phase committed as its result (eval/results/README.md). */
const HEADLINE = [
  { id: "phase7-adversarial-agent-r2", label: "Adversarial, through the agent" },
  { id: "phase7-e2e-dev-agent-rescored", label: "End-to-end factual (dev), agent" },
  { id: "phase6-e2e-sonnet-r2", label: "End-to-end factual, Claude + MCP" },
  { id: "phase6-explanation-sonnet-r2", label: "Explanations, Claude + MCP" },
];

function answererLabel(a: string | null): string {
  if (!a) return "?";
  if (a.startsWith("agent-")) return `Our agent (${a.slice(6)})`;
  if (a.startsWith("claude-code")) return "Claude Code + MCP server";
  if (a.startsWith("claude-api")) return `Claude API (${a.slice(11)})`;
  if (a.startsWith("openai-api")) return `OpenAI API (${a.slice(11)})`;
  if (a === "gold" || a === "null") return `Harness self-check (${a})`;
  return a;
}

export function EvaluationPage({ runId }: { runId?: string }) {
  const runs = useQuery({ queryKey: ["eval-runs"], queryFn: api.evalRuns });
  const navigate = useNavigate();
  const selected = runId ?? HEADLINE[0]!.id;
  const run = useQuery({
    queryKey: ["eval-run", selected],
    queryFn: () => api.evalRun(selected),
    retry: false,
  });
  const byId = useMemo(
    () => new Map((runs.data?.runs ?? []).map((r) => [r.run_id, r])),
    [runs.data],
  );
  const s = run.data?.summary.summary;
  const errors = (s?.error_categories ?? {}) as Record<string, number>;
  const latency = {
    p50: s?.latency_p50_s as number | undefined,
    p95: s?.latency_p95_s as number | undefined,
  };

  return (
    <div>
      <PageHeader
        title="Evaluation"
        lede="A 173-question benchmark scored deterministically: the right number from the right edition, the right behaviour (answer, ask or decline) and the right tools. Held-out questions (test split) are never tuned on."
      />
      {runs.isPending ? (
        <Loading lines={4} />
      ) : runs.error ? (
        <ErrorState error={runs.error} retry={() => void runs.refetch()} />
      ) : (
        <>
          <div className="mb-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {HEADLINE.map((h) => {
              const r = byId.get(h.id);
              return (
                <Link
                  key={h.id}
                  to="/eval/$runId"
                  params={{ runId: h.id }}
                  className={`rounded-lg border bg-card p-4 hover:border-accent ${h.id === selected ? "border-accent" : "border-rule"}`}
                >
                  <p className="text-sm text-muted">{h.label}</p>
                  <p className="num mt-1 font-serif text-4xl font-semibold text-ink">
                    {r?.accuracy !== null && r?.accuracy !== undefined ? fmtPct(r.accuracy) : "—"}
                  </p>
                  <p className="num text-sm text-ink-2">
                    {r ? `${r.correct} of ${r.n} correct` : "not run yet"}
                  </p>
                </Link>
              );
            })}
          </div>

          <section aria-labelledby="base-h" className="mb-8">
            <h2 id="base-h" className="mb-2 font-serif text-2xl font-semibold">
              Lift over baselines
            </h2>
            <EmptyState title="Web-search and Genie baselines run in Phase 10">
              The same questions answered by a web-search assistant and by Databricks Genie over the
              raw tables. Until then this page reports our systems only.
            </EmptyState>
          </section>

          <section aria-labelledby="run-h" className="mb-8">
            <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
              <h2 id="run-h" className="font-serif text-2xl font-semibold">
                {run.data ? answererLabel(run.data.summary.answerer) : "Run"}{" "}
                <span className="font-mono text-sm font-normal text-muted">{selected}</span>
              </h2>
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-ink-2">Any committed run</span>
                <select
                  value={selected}
                  onChange={(e) =>
                    navigate({ to: "/eval/$runId", params: { runId: e.target.value } })
                  }
                  className="rounded-md border border-rule bg-card px-2 py-1.5"
                >
                  {(runs.data?.runs ?? []).map((r: EvalRunSummary) => (
                    <option key={r.run_id} value={r.run_id}>
                      {r.run_id} ({r.correct}/{r.n})
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {run.isPending ? (
              <Loading lines={5} />
            ) : run.error ? (
              <ErrorState error={run.error} />
            ) : s ? (
              <div className="grid gap-6 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
                <div className="space-y-4">
                  <Breakdown title="By suite" rows={s.by_suite ?? {}} />
                  <Breakdown title="By split" rows={s.by_split ?? {}} />
                  {Object.keys(errors).length > 0 && (
                    <div className="rounded-lg border border-rule bg-card p-4 text-sm">
                      <h3 className="font-semibold text-ink">Error categories</h3>
                      <ul className="num mt-2 space-y-1">
                        {Object.entries(errors).map(([k, v]) => (
                          <li key={k} className="flex justify-between gap-4">
                            <span className="text-ink-2">{k.replace(/_/g, " ")}</span>
                            <span>{v}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {latency.p50 !== undefined && (
                    <p className="num text-sm text-ink-2">
                      Latency p50 {latency.p50.toFixed(1)} s · p95 {latency.p95?.toFixed(1)} s
                    </p>
                  )}
                </div>
                <div className="overflow-x-auto rounded-lg border border-rule bg-card">
                  <table className="w-full text-sm">
                    <caption className="sr-only">Every scored question in this run</caption>
                    <thead>
                      <tr className="border-b border-rule text-left text-muted">
                        <th scope="col" className="px-3 py-2 font-medium">
                          Result
                        </th>
                        <th scope="col" className="px-3 py-2 font-medium">
                          Question
                        </th>
                        <th scope="col" className="px-3 py-2 font-medium">
                          Split
                        </th>
                        <th scope="col" className="px-3 py-2 font-medium">
                          Tools
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {run.data!.items.map((it) => (
                        <tr
                          key={it.question_id}
                          id={it.question_id}
                          className="border-b border-rule/60 align-top"
                        >
                          <td className="whitespace-nowrap px-3 py-2">
                            {it.correct ? (
                              <span className="inline-flex items-center gap-1 text-good">
                                <Icon name="check" /> Correct
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 text-critical">
                                <Icon name="caution" />{" "}
                                {it.error_category?.replace(/_/g, " ") ?? "Wrong"}
                              </span>
                            )}
                          </td>
                          <td className="px-3 py-2">
                            <span className="text-ink">{it.question}</span>
                            <br />
                            <span className="font-mono text-xs text-muted">{it.question_id}</span>
                          </td>
                          <td className="px-3 py-2 text-ink-2">{it.split}</td>
                          <td className="px-3 py-2 font-mono text-xs text-ink-2">
                            {it.tools_called.join(", ")}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : null}
          </section>
        </>
      )}
    </div>
  );
}

function Breakdown({
  title,
  rows,
}: {
  title: string;
  rows: Record<string, { n: number; correct: number; accuracy: number }>;
}) {
  return (
    <div className="rounded-lg border border-rule bg-card p-4 text-sm">
      <h3 className="font-semibold text-ink">{title}</h3>
      <ul className="num mt-2 space-y-2">
        {Object.entries(rows).map(([k, v]) => (
          <li key={k}>
            <div className="flex justify-between gap-4">
              <span className="text-ink-2">{k.replace(/_/g, " ")}</span>
              <span>
                {v.correct}/{v.n} · {fmtPct(v.accuracy)}
              </span>
            </div>
            <div className="mt-1 h-1.5 rounded-full bg-paper-2" aria-hidden>
              <div
                className="h-full rounded-full bg-[var(--seq-3)]"
                style={{ width: `${v.accuracy * 100}%` }}
              />
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
