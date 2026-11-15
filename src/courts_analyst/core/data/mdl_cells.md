# `mdl_cells.csv`: MDL case counts precomputed from the civil IDB

The IBM watsonx Orchestrate toolkit ships the official tables but not the FJC
civil Integrated Database (IDB, about 450 MB), so `explain_change` can't run
its MDL driver there. This file carries the only IDB numbers that driver needs.

| Column | Meaning |
| --- | --- |
| `rule` | `filed` (directly filed MDL cases, by filing fiscal year), `terminated` (direct-filed or transferred MDL cases, by termination fiscal year), `pending` (direct-filed or transferred MDL cases pending on September 30 of the fiscal year) |
| `court` | IDB district code (e.g. `FL-N`) |
| `mdl_docket` | MDL docket number (`?` when the record has none) |
| `fiscal_year` | Federal fiscal year (October 1 to September 30) |
| `cases` | Number of IDB records |

- **Source:** FJC civil IDB release with case status as of June 30, 2026
  (`idb-report.json` record checksum `3805976:3f4c19a934221730cf2411cbef9f8a1e`).
- **Method:** the same queries `explain_change` runs on the IDB
  (`_MDL_SQL["filed"]`, `_MDL_SQL["terminated"]`, `_MDL_PENDING_SQL` in
  `core/explain.py`), over every district, FY2016–FY2025.
- **Small cells dropped:** only cells of 25 or more cases are kept: 1,278 of
  4,236 cells, 3,446,360 of 3,462,026 MDL case-rows (99.5%).
- **Checks:** N.D. Fla. directly filed MDL cases FY2019 → FY2020 net +200,568
  (MDL 2885: 1,345 → 202,362), matching the explanation bank's +200,570 within
  the dropped small cells; D.N.J. MDL 2738 FY2023 → FY2024: 15,207 → 5,176.
