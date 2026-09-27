import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { PageHeader } from "@/components/Layout";
import { Markdown } from "@/components/Markdown";
import { ErrorState, Loading } from "@/components/States";

export function MethodologyPage() {
  const topics = useQuery({ queryKey: ["methodology"], queryFn: api.methodology });
  const [topic, setTopic] = useState<string | null>(null);
  const current = topic ?? topics.data?.topics[0]?.topic ?? null;
  const note = useQuery({
    queryKey: ["methodology", current],
    queryFn: () => api.methodologyTopic(current!),
    enabled: !!current,
  });
  const glossary = useQuery({ queryKey: ["glossary"], queryFn: api.glossary });
  const [filter, setFilter] = useState("");
  const terms = useMemo(() => {
    const f = filter.trim().toLowerCase();
    return (glossary.data?.terms ?? []).filter(
      (t) =>
        !f ||
        t.term.toLowerCase().includes(f) ||
        t.aliases.some((a) => a.toLowerCase().includes(f)) ||
        t.definition.toLowerCase().includes(f),
    );
  }, [glossary.data, filter]);

  return (
    <div>
      <PageHeader
        title="Methodology"
        lede="Where the numbers come from, how editions and revisions are handled, and what this service won't do. The same notes the MCP server serves to AI clients."
      />
      <div className="grid gap-8 lg:grid-cols-[14rem_minmax(0,1fr)]">
        <nav aria-label="Methodology topics" className="space-y-1">
          {topics.isPending && <Loading lines={4} />}
          {topics.error && <ErrorState error={topics.error} />}
          {topics.data?.topics.map((t) => (
            <button
              key={t.topic}
              type="button"
              onClick={() => setTopic(t.topic)}
              aria-current={t.topic === current ? "true" : undefined}
              className={`block w-full rounded-md px-3 py-2 text-left text-sm ${
                t.topic === current
                  ? "bg-paper-2 font-medium text-ink"
                  : "text-ink-2 hover:bg-paper-2"
              }`}
            >
              {t.title}
            </button>
          ))}
          <a
            href="#sources"
            className="block rounded-md px-3 py-2 text-sm text-ink-2 hover:bg-paper-2"
          >
            Data sources and limits
          </a>
          <a
            href="#glossary"
            className="block rounded-md px-3 py-2 text-sm text-ink-2 hover:bg-paper-2"
          >
            Glossary
          </a>
        </nav>
        <div className="min-w-0 space-y-10">
          <article className="max-w-3xl">
            {note.isPending && current ? (
              <Loading lines={8} />
            ) : note.error ? (
              <ErrorState error={note.error} />
            ) : note.data ? (
              <Markdown text={note.data.markdown} className="prose-answer text-ink" />
            ) : null}
          </article>

          <section id="sources" aria-labelledby="src-h" className="max-w-3xl">
            <h2 id="src-h" className="font-serif text-2xl font-semibold">
              Data sources and limits
            </h2>
            <div className="prose-answer mt-2 text-ink">
              <p>
                <strong>Official tables</strong> from uscourts.gov: Judicial Business (tables X-1A,
                C-1, C-5) and Judicial Facts and Figures (tables 6.1–6.3), every edition covering
                FY2016–FY2025, with national rows back to 1990. Each figure names its edition, table
                and cell.
              </p>
              <p>
                <strong>The FJC Integrated Database</strong> (civil cases active FY2015–FY2025),
                with party names removed at build time. Statistics on fewer than 10 cases are
                withheld.
              </p>
              <p>
                <strong>Not covered:</strong> judge-level data (by Judicial Conference policy),
                party names, bankruptcy and appellate courts, and criminal case records.
              </p>
              <p>
                <strong>The district map</strong> draws districts from county boundaries (U.S.
                Census, via us-atlas). No machine-readable county-to-district list ships with the
                data, so each county is assigned to the district most of its IDB civil filings went
                to, within its own state; counties with a weak majority take their neighbours'
                district. A few border counties may still be misplaced. Figures never depend on the
                map: the ranking table is exact.
              </p>
            </div>
          </section>

          <section id="glossary" aria-labelledby="gl-h">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <h2 id="gl-h" className="font-serif text-2xl font-semibold">
                Glossary
              </h2>
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-ink-2">Filter terms</span>
                <input
                  type="search"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  className="rounded-md border border-rule bg-card px-2 py-1.5"
                />
              </label>
            </div>
            {glossary.isPending ? (
              <Loading lines={6} />
            ) : (
              <dl className="mt-4 grid gap-4 md:grid-cols-2">
                {terms.map((t) => (
                  <div key={t.term} className="rounded-lg border border-rule bg-card p-4">
                    <dt className="font-semibold capitalize text-ink">{t.term}</dt>
                    <dd className="mt-1 text-sm text-ink-2">{t.definition}</dd>
                    {t.source && <dd className="mt-1 text-xs text-muted">Source: {t.source}</dd>}
                  </div>
                ))}
              </dl>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
