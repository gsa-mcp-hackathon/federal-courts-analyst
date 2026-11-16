// Build public/geo/districts.topo.json: the 90 district courts on the 50
// states + DC, from us-atlas counties (Albers USA, Alaska and Hawaii inset)
// and the IDB-derived county → district crosswalk
// (src/geo/county-districts.json, from `python -m courts_analyst.pipeline.geo`).
//
// Counties the crosswalk misses, or assigns with a weak majority (< 60% of
// their in-state cases), take the district most of their same-state
// neighbours have, so boundaries follow whole, contiguous counties. Territories
// (PR, VI, GU, MP) aren't in us-atlas; the map draws them as labelled tiles.
//
//   npm run geo            # rebuild
//   npm run geo -- --check # fail if the committed file is stale
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { feature, mergeArcs, neighbors } from "topojson-client";
import { topology } from "topojson-server";
import { presimplify, simplify, quantile } from "topojson-simplify";

const require = createRequire(import.meta.url);
const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const OUT = join(root, "public", "geo", "districts.topo.json");
const REPORT = join(root, "src", "geo", "districts-report.json");

const counties = require("us-atlas/counties-albers-10m.json");
const cw = JSON.parse(readFileSync(join(root, "src/geo/county-districts.json"), "utf8"));
const WEAK = 0.6;

const geoms = counties.objects.counties.geometries;
const stateOf = (id) => cw.state_fips[id.slice(0, 2)];
const assigned = new Map();
const strong = new Set();
for (const g of geoms) {
  const single = cw.single_district_states[stateOf(g.id)];
  const c = cw.counties[g.id];
  if (single) {
    assigned.set(g.id, single);
    strong.add(g.id);
  } else if (c) {
    assigned.set(g.id, c.district);
    if (c.share >= WEAK) strong.add(g.id);
  }
}

// Fill and smooth from same-state neighbours, until nothing changes.
const nbrs = neighbors(geoms);
const changes = [];
for (let pass = 0; pass < 10; pass++) {
  let changed = 0;
  geoms.forEach((g, i) => {
    if (strong.has(g.id)) return;
    const votes = new Map();
    for (const j of nbrs[i]) {
      const h = geoms[j];
      if (stateOf(h.id) !== stateOf(g.id) || !assigned.has(h.id)) continue;
      const w = strong.has(h.id) ? 2 : 1;
      const d = assigned.get(h.id);
      votes.set(d, (votes.get(d) ?? 0) + w);
    }
    if (!votes.size) return;
    const [best, n] = [...votes].sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1))[0];
    const total = [...votes.values()].reduce((a, b) => a + b, 0);
    const current = assigned.get(g.id);
    // Missing: take the neighbours' district. Weak: move only when at least
    // two thirds of the neighbour weight agrees on another district.
    if (current === undefined || (best !== current && n / total >= 2 / 3)) {
      assigned.set(g.id, best);
      changes.push({ county: g.id, from: current ?? null, to: best, pass });
      changed++;
    }
  });
  if (!changed) break;
}

const byDistrict = new Map();
geoms.forEach((g) => {
  const d = assigned.get(g.id);
  if (!d) return;
  if (!byDistrict.has(d)) byDistrict.set(d, []);
  byDistrict.get(d).push(g);
});

const districtFeatures = [...byDistrict.entries()]
  .sort(([a], [b]) => (a < b ? -1 : 1))
  .map(([id, gs]) => ({
    type: "Feature",
    id,
    properties: { counties: gs.length },
    geometry: feature(counties, mergeArcs(counties, gs)).geometry,
  }));
const states = feature(counties, counties.objects.states);

let topo = topology(
  { districts: { type: "FeatureCollection", features: districtFeatures }, states },
  1e5,
);
topo = presimplify(topo);
topo = simplify(topo, quantile(topo, 0.35));
const text = JSON.stringify(topo);
const report = {
  districts: districtFeatures.length,
  counties: geoms.length,
  unassigned: geoms.filter((g) => !assigned.has(g.id)).map((g) => g.id),
  smoothed: changes,
  bytes: text.length,
};

if (process.argv.includes("--check")) {
  const old = readFileSync(OUT, "utf8");
  if (old.trim() !== text) {
    console.error("public/geo/districts.topo.json is stale: run `npm run geo`.");
    process.exit(1);
  }
  console.error("districts.topo.json is up to date.");
} else {
  mkdirSync(dirname(OUT), { recursive: true });
  writeFileSync(OUT, text + "\n");
  writeFileSync(REPORT, JSON.stringify(report, null, 1) + "\n");
  console.error(
    `wrote ${report.districts} districts (${(text.length / 1024).toFixed(0)} KB); ` +
      `${changes.length} counties filled or smoothed; ${report.unassigned.length} unassigned`,
  );
}
