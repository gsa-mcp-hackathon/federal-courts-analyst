import { editionLabel, fmtCi, fmtCount, fmtPct, fmtSigned, fmtValue } from "./format";

describe("number formatting", () => {
  it("prints published values as the tables do", () => {
    expect(fmtValue(322)).toBe("322");
    expect(fmtValue(290896)).toBe("290,896");
    expect(fmtValue(8.5)).toBe("8.5");
    expect(fmtValue(null)).toBe("—");
    expect(fmtValue(Number.NaN)).toBe("—");
  });

  it("signs changes with a true minus", () => {
    expect(fmtSigned(173)).toBe("+173");
    expect(fmtSigned(-232)).toBe("−232");
    expect(fmtSigned(0)).toBe("0");
  });

  it("never renders a suppressed count as 0", () => {
    expect(fmtCount(null)).toBe("fewer than 10");
    expect(fmtCount(0, true)).toBe("fewer than 10");
    expect(fmtCount(undefined)).toBe("fewer than 10");
    expect(fmtCount(1234)).toBe("1,234");
    expect(fmtCount(0)).toBe("0");
  });

  it("formats shares and intervals", () => {
    expect(fmtPct(0.421)).toBe("42.1%");
    expect(fmtPct(-0.05, true)).toBe("−5%");
    expect(fmtCi(4.1, 5.25)).toBe("95% CI 4.1–5.3");
    expect(fmtCi(null, 3)).toBe("");
  });

  it("labels editions for badges", () => {
    expect(editionLabel("JFF-2023")).toBe("JFF 2023");
  });
});
