// A tiny seeded property-test helper (no extra dependency): runs `prop` on
// random (start, end, changes[]) cases and fails with the first counterexample.
type Prop = (start: number, end: number, changes: number[]) => boolean;

function rng(seed: number) {
  return () => {
    seed = (seed * 1664525 + 1013904223) % 4294967296;
    return seed / 4294967296;
  };
}

export default {
  assert(prop: Prop, runs = 300, seed = 20260927) {
    const r = rng(seed);
    const int = (lo: number, hi: number) => Math.round(lo + r() * (hi - lo));
    for (let i = 0; i < runs; i++) {
      const start = int(0, 5000);
      const end = int(0, 5000);
      const changes = Array.from({ length: int(0, 12) }, () => int(-800, 800));
      if (!prop(start, end, changes))
        throw new Error(
          `property failed for start=${start} end=${end} changes=${JSON.stringify(changes)}`,
        );
    }
  },
};
