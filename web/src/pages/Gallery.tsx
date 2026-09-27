// /dev/gallery: every signature component with fixed mock data, for design
// review and visual regression tests (no API calls).
import { SpecChart, ContributorWaterfall, VintageChart } from "@/components/charts";
import { ClarifyChips, DocketCard, ToolTrace } from "@/components/agent";
import { PageHeader } from "@/components/Layout";
import {
  DeclineCard,
  ProvenanceBadge,
  ReconciliationBadge,
  RevisionChip,
  SuppressedCell,
  WarningCallout,
} from "@/components/Provenance";
import { MOCK } from "@/test/mocks";

export function GalleryPage() {
  return (
    <div className="space-y-10">
      <PageHeader title="Component gallery" lede="Signature components with fixed data." />
      <Section title="Provenance">
        <div className="flex flex-wrap items-center gap-3">
          <span className="num font-serif text-4xl font-semibold">322</span>
          <ProvenanceBadge p={MOCK.provenance} />
          <RevisionChip status="revised" firstValue={554} firstEdition="JB-2020" />
          <ReconciliationBadge
            b={{
              status: "matched",
              official_value: 291851,
              idb_value: 290951,
              variance: -900,
              variance_pct: -0.31,
              explanation: null,
            }}
          />
          <ReconciliationBadge
            b={{
              status: "explained_variance",
              official_value: 57000,
              idb_value: 58200,
              variance: 1200,
              variance_pct: 2.1,
              explanation: "Restated in a later edition.",
            }}
          />
          <ReconciliationBadge
            b={{
              status: "unexplained",
              official_value: 84000,
              idb_value: 89400,
              variance: 5400,
              variance_pct: 6.4,
              explanation: null,
            }}
          />
          <SuppressedCell n={null} suppressed />
          <SuppressedCell n={1234} />
        </div>
      </Section>
      <Section title="Warnings and declines">
        <div className="grid gap-3 md:grid-cols-2">
          <WarningCallout
            w={{
              code: "inferred_not_official",
              severity: "caution",
              message:
                "The explanation of the FY2020 revision is our inference from the district figures, not an official statement.",
            }}
          />
          <WarningCallout
            w={{
              code: "data_break",
              severity: "info",
              message: "COVID-19 national emergency (March 13, 2020) disrupted court operations.",
            }}
          />
          <WarningCallout
            w={{
              code: "suppressed",
              severity: "block",
              message: "Groups with fewer than 10 cases are shown as suppressed.",
            }}
          />
          <DeclineCard d={MOCK.decline} onAsk={() => undefined} />
        </div>
      </Section>
      <Section title="Charts">
        <div className="grid gap-4 lg:grid-cols-2">
          <VintageChart
            lines={MOCK.vintageLines}
            unit="weighted filings per judgeship"
            title="Weighted civil filings per judgeship, national: every edition"
            source="Mock data."
          />
          <ContributorWaterfall
            start={381}
            end={554}
            contributions={MOCK.contributions}
            startLabel="FY2019"
            endLabel="FY2020"
            title="What moved FY2019 → FY2020"
            unit="per judgeship"
            source="Mock data."
          />
          <SpecChart spec={MOCK.editionsSpec} />
          <SpecChart spec={MOCK.barSpec} />
        </div>
      </Section>
      <Section title="Agent">
        <div className="grid gap-4 md:grid-cols-2">
          <ClarifyChips ev={MOCK.clarify} onChoose={() => undefined} />
          <DocketCard card={MOCK.docket} />
          <div className="md:col-span-2">
            <ToolTrace steps={MOCK.steps} />
          </div>
        </div>
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section aria-label={title}>
      <h2 className="mb-3 font-serif text-xl font-semibold">{title}</h2>
      {children}
    </section>
  );
}
