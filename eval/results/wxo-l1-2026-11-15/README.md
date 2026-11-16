# Layer 1 desk runs, 2026-11-15 (step 10)

`orchestrate evaluations` output for the three desk tests (`l1desk`,
`l1desk2`, `l1desk3`), after deploying the `keep_answer` preview_id check.
Check with `uv run courts-eval preview-check <dir>`.

| Folder | Server | Instructions | Runs |
| --- | --- | --- | --- |
| `v8-pr9/` | #9 (preview_id) | v8 | 6 (l1desk r3 hung and was stopped) |
| `v8/` | #9 + #10 (typography-tolerant digest) | v8 | 6 |
| `v12/` | #9 + #10 | v12 | 6 |

v12 was rejected (3 preview violations; each confirmed call without a
preview_id was refused by the server). The agent stays on v8.
| `v8-pr12/` | #9 + #10 + #12 (gate places re-run numbers; ask_office checked before asking) | v8 | 6 |

On the #12 server (v8, deployed): 14 confirmed calls, 3 violations, all refused by the server; 5 of 6 runs ended in a save after a preview and a yes. Dev on the same setup: `../20261116T005129Z-wxo-all-dev-subset.md`.
