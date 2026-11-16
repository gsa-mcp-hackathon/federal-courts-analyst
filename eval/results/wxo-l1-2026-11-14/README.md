# Layer 1 desk runs, 2026-11-14 to 15

`orchestrate evaluations` output for the two desk tests
(`eval/wxo/tests/l1desk`: `desk_keep_answer_priya`;
`eval/wxo/tests/l1desk2`: `desk_save_and_status_priya`), one pair per round.
Check the preview rule with `uv run courts-eval preview-check <dir>`.

| Round | Instructions | `l1desk` | `l1desk2` |
| --- | --- | --- | --- |
| r1 | v8 | `2026-11-14_17-58-51` | `2026-11-14_18-01-37` |
| dev | v9 | `2026-11-14_21-09-40` | `2026-11-14_21-10-51` |
| dev | v10 | `2026-11-14_22-44-00` | `2026-11-14_22-46-56` |
| dev | v11 | `2026-11-15_00-54-50` | `2026-11-15_00-57-28` |
| held-out | v8 | `2026-11-15_02-48-21` | `2026-11-15_02-51-18` |

The mapping comes from the `xfer/l1/run-*-l1dirs.txt` files on the
transfer-only branch `xfer/eval-runs-1114`, which was deleted afterwards.
