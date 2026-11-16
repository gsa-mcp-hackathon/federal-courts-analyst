// Fixed data for the component gallery and unit tests (shapes from the
// generated API types; values from the real FY2020 story).
import type { Contribution, Decline, Provenance } from "@/api/types";
import type { ChartSpec, ClarifyEvent, DocketCard } from "@/api/types.gen";
import type { ToolStep } from "@/api/turn";
import type { VintageLine } from "@/lib/vintage";

const provenance: Provenance = {
  source: "official_table",
  table_code: "6.2",
  series: "Judicial Facts and Figures",
  edition: "JFF-2025",
  period: { fiscal_year: 2020, period_end: "2020-09-30", period_type: "fiscal_year" },
  definition:
    "Civil filings multiplied by Federal Judicial Center case weights, divided by authorized judgeships.",
  url: "https://www.uscourts.gov/sites/default/files/document/jff_6_2_0930.2025.xlsx",
  cell_ref: "Table 6.2!D5",
  revision_status: "revised",
  first_published: {
    value: 554,
    edition: "JB-2020",
    table_code: "X-1A",
    url: null,
    cell_ref: null,
  },
  reconciliation: null,
  dataset_release: null,
  note: null,
  later_revisions: [],
};

const decline: Decline = {
  reason: "judge_level",
  message:
    "This server can't rank, compare, name or profile individual judges: the data has no judge identifiers, by Judicial Conference policy.",
  policy: "Judicial Conference policy on judge-identifying statistics (IDB documentation).",
  alternative: "Median time to disposition for civil cases in S.D.N.Y., FY2024",
};

const series = (edition: string, pts: [number, number][]) =>
  pts.map(([fy, value]) => ({
    fy,
    value,
    edition,
    table: edition.startsWith("JB") ? "X-1A" : "6.2",
  }));

const vintageLines: VintageLine[] = [
  {
    key: "first",
    label: "As first published",
    kind: "first",
    rank: -1,
    points: [
      [2016, 355],
      [2017, 341],
      [2018, 367],
      [2019, 381],
      [2020, 554],
      [2021, 434],
      [2022, 355],
      [2023, 431],
    ].map(([fy, v]) => ({ fy: fy!, value: v!, edition: `JB-${fy}`, table: "X-1A" })),
  },
  {
    key: "JFF-2020",
    label: "JFF-2020",
    kind: "edition",
    rank: 0,
    points: series("JFF-2020", [
      [2016, 355],
      [2017, 341],
      [2018, 367],
      [2019, 381],
      [2020, 554],
    ]),
  },
  {
    key: "JFF-2023",
    label: "JFF-2023",
    kind: "edition",
    rank: 1,
    points: series("JFF-2023", [
      [2019, 332],
      [2020, 322],
      [2021, 330],
      [2022, 318],
      [2023, 350],
    ]),
  },
];

const contributions: Contribution[] = [
  {
    key: "FL-N",
    label: "N.D. Fla.",
    value_from: 5,
    value_to: 211,
    change: 206,
    share_of_change: 1.19,
    key_contributor: true,
  },
  {
    key: "TX-S",
    label: "S.D. Tex.",
    value_from: 12,
    value_to: 9,
    change: -3,
    share_of_change: -0.02,
    key_contributor: false,
  },
  {
    key: "NJ",
    label: "D.N.J.",
    value_from: 14,
    value_to: 11,
    change: -3,
    share_of_change: -0.02,
    key_contributor: false,
  },
  {
    key: "CA-C",
    label: "C.D. Cal.",
    value_from: 18,
    value_to: 15,
    change: -3,
    share_of_change: -0.02,
    key_contributor: false,
  },
];

const editionsSpec: ChartSpec = {
  kind: "editions",
  title: "Weighted civil filings per judgeship, national, FY2020: every edition",
  x_label: "Edition",
  y_label: "Weighted civil filings per judgeship",
  unit: "weighted filings per judgeship",
  series: [
    {
      name: "Published value",
      points: [
        { x: "JB-2020", y: 554, label: null },
        { x: "JFF-2020", y: 554, label: null },
        { x: "JFF-2021", y: 554, label: null },
        { x: "JFF-2022", y: 554, label: null },
        { x: "JFF-2023", y: 322, label: null },
        { x: "JFF-2024", y: 322, label: null },
        { x: "JFF-2025", y: 322, label: null },
      ],
    },
  ],
  source: "JB-2020 Table X-1A; JFF-2020–2025 Table 6.2",
  call_id: "c1",
};

const barSpec: ChartSpec = {
  kind: "bar",
  title: "Weighted filings per judgeship, FY2024",
  x_label: "Court",
  y_label: "Weighted filings per judgeship",
  unit: "weighted filings per judgeship",
  series: [
    {
      name: "JB-2024",
      points: [
        { x: "N.D. Fla.", y: 4256, label: null },
        { x: "E.D. Cal.", y: 684, label: null },
        { x: "D.N.J.", y: 626, label: null },
        { x: "E.D.N.C.", y: 621, label: null },
        { x: "C.D. Cal.", y: 612, label: null },
      ],
    },
  ],
  source: "JB-2024, Table X-1A",
  call_id: "c2",
};

const clarify: ClarifyEvent = {
  seq: 5,
  type: "clarify",
  turn_id: "t1",
  clarify_id: "0123456789ab",
  clarification: {
    parameter: "measure",
    question: "Which filings per judgeship: weighted or unweighted, total or civil only?",
    choices: [
      {
        value: "weighted_total_filings_per_judgeship",
        label: "Weighted total filings per judgeship",
        description: null,
      },
      {
        value: "total_filings_per_judgeship",
        label: "Total filings per judgeship (unweighted)",
        description: null,
      },
      {
        value: "weighted_civil_filings_per_judgeship",
        label: "Weighted civil filings per judgeship",
        description: null,
      },
      {
        value: "civil_filings_per_judgeship",
        label: "Civil filings per judgeship (unweighted)",
        description: null,
      },
    ],
    default: "weighted_total_filings_per_judgeship",
  },
};

const docket: DocketCard = {
  origin: "idb_sample",
  court: "N.D. Fla.",
  docket_number: "8:20-cv-49045",
  filing_date: "2020-07-06",
  nature_of_suit: "Personal injury/product liability",
  cause: "&lt;script&gt;alert(1)&lt;/script&gt; 28:1332 Diversity",
  url: "https://www.courtlistener.com/?type=r&q=docketNumber%3A%2220-cv-49045%22&court=flnd",
  note: "match may be inexact",
};

const steps: ToolStep[] = [
  {
    call: {
      seq: 2,
      type: "tool_call",
      call_id: "c1",
      server: "courts-analyst",
      tool: "explain_change",
      arguments: {
        measure: "weighted_civil_filings_per_judgeship",
        court: "US",
        period_from: 2019,
        period_to: 2020,
      },
    },
    result: {
      seq: 3,
      type: "tool_result",
      call_id: "c1",
      server: "courts-analyst",
      tool: "explain_change",
      status: "ok",
      result: { status: "ok" },
      error: null,
      latency_ms: 651.6,
    },
  },
  {
    call: {
      seq: 4,
      type: "tool_call",
      call_id: "c2",
      server: "courts-analyst",
      tool: "find_cases",
      arguments: { courts: ["FL-N"], fy_from: 2020, fy_to: 2020 },
    },
  },
];

export const MOCK = {
  provenance,
  decline,
  vintageLines,
  contributions,
  editionsSpec,
  barSpec,
  clarify,
  docket,
  steps,
};
