import fc from "./fc";
import { binIndex, binsFor } from "@/components/DistrictMap";
import { MOCK } from "@/test/mocks";
import { editionHistory, rampStep, revisionGaps, vintageLines } from "./vintage";
import { waterfall } from "./waterfall";

describe("VintageChart data", () => {
  it("finds the years a later edition revised", () => {
    const gaps = revisionGaps(MOCK.vintageLines);
    const fy2020 = gaps.find((g) => g.fy === 2020)!;
    expect(fy2020).toMatchObject({
      first: 554,
      latest: 322,
      firstEdition: "JB-2020",
      latestEdition: "JFF-2023",
    });
    // FY2018 was never revised.
    expect(gaps.some((g) => g.fy === 2018)).toBe(false);
  });

  it("builds one line per edition and drops one-year editions", () => {
    const lines = vintageLines(null, [
      {
        edition: "JB-2020",
        series: null,
        url: null,
        points: [
          {
            fiscal_year: 2020,
            value: 554,
            table_code: "X-1A",
            cell_ref: null,
            period: { fiscal_year: 2020, period_end: "2020-09-30", period_type: "fiscal_year" },
          },
        ],
      },
      {
        edition: "JFF-2023",
        series: null,
        url: null,
        points: [2019, 2020, 2021].map((fy) => ({
          fiscal_year: fy,
          value: 300 + fy - 2019,
          table_code: "6.2",
          cell_ref: null,
          period: {
            fiscal_year: fy,
            period_end: `${fy}-09-30`,
            period_type: "fiscal_year" as const,
          },
        })),
      },
    ]);
    expect(lines.map((l) => l.key)).toEqual(["JFF-2023"]);
    expect(lines[0]!.points).toHaveLength(3);
  });

  it("flags the editions that changed a figure", () => {
    const h = editionHistory([
      { value: 554, edition: "JB-2020", table_code: "X-1A" },
      { value: 554, edition: "JFF-2022", table_code: "6.2" },
      { value: 322, edition: "JFF-2023", table_code: "6.2" },
    ]);
    expect(h.map((e) => e.changed)).toEqual([false, false, true]);
  });

  it("ramps older editions lighter", () => {
    expect([0, 1, 2, 3, 4].map((r) => rampStep(r, 5))).toEqual([0, 1, 2, 2, 3]);
    expect(rampStep(0, 1)).toBe(3);
  });
});

describe("ContributorWaterfall data", () => {
  it("lands exactly on the end value", () => {
    const steps = waterfall(381, 554, MOCK.contributions, 2, "FY2019", "FY2020");
    expect(steps[0]).toMatchObject({ kind: "start", to: 381 });
    expect(steps.at(-1)).toMatchObject({ kind: "end", to: 554 });
    const inner = steps.slice(1, -1);
    expect(inner.at(-1)!.to).toBe(554);
    expect(inner.some((s) => s.label === "All other")).toBe(true);
  });

  it("always sums to the change (property test)", () => {
    fc.assert((start, end, changes) => {
      const cs = changes.map((c, i) => ({
        key: String(i),
        label: `c${i}`,
        value_from: 0,
        value_to: c,
        change: c,
        share_of_change: null,
        key_contributor: false,
      }));
      const steps = waterfall(start, end, cs, 3);
      const sum = steps.slice(1, -1).reduce((s, x) => s + x.change, 0);
      return Math.abs(start + sum - end) < 1e-6 && steps.at(-1)!.to === end;
    });
  });
});

describe("map bins", () => {
  it("uses the Judicial Conference thresholds for weighted filings", () => {
    const bins = binsFor([100, 500, 700], true);
    expect(bins.map((b) => b.label)).toEqual(["Under 430", "430–600", "600–1,000", "Over 1,000"]);
    expect([429, 430, 600, 999, 1161].map((v) => binIndex(v, bins))).toEqual([0, 1, 2, 2, 3]);
  });

  it("uses quartiles otherwise", () => {
    const bins = binsFor([1, 2, 3, 4, 5, 6, 7, 8], false);
    expect(bins).toHaveLength(4);
    expect(binIndex(1, bins)).toBe(0);
    expect(binIndex(8, bins)).toBe(3);
  });
});
