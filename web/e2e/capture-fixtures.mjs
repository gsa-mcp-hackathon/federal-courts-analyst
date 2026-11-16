// Capture the REST responses the e2e journeys use from a running backend
// (full data: `make serve-http PORT=8000`) into e2e/fixtures/api.json.
//   node e2e/capture-fixtures.mjs [http://127.0.0.1:8000]
import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { URLS, keyOf } from "./fixture-urls.mjs";

const base = process.argv[2] ?? "http://127.0.0.1:8000";
const out = {};
for (const url of URLS) {
  const res = await fetch(base + url);
  out[keyOf(url)] = { status: res.status, body: await res.json() };
  if (!res.ok) console.error(`${res.status} ${url}`);
}
const file = join(dirname(fileURLToPath(import.meta.url)), "fixtures", "api.json");
writeFileSync(file, JSON.stringify(out) + "\n");
console.error(`wrote ${Object.keys(out).length} responses to ${file}`);
