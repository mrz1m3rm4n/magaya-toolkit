---
name: update-api-coverage
description: "Trigger: finished/implemented a Magaya API method, mark method done, update API coverage. Flip the method to done in README.md and recompute the coverage tallies."
license: Apache-2.0
metadata:
  author: mrz1m3rm4n
  version: "1.0"
---

## Activation Contract

Run when a Magaya API method's read support is finished — client call, typed
model/parser (if it returns data), a facade resource or use case exposing it,
and a passing test. Also run to correct a stale status. `README.md` is the
single source of truth for coverage.

## Hard Rules

- Edit ONLY between the `<!-- API-COVERAGE:START -->` and
  `<!-- API-COVERAGE:END -->` markers in `README.md`.
- Never add, rename, or remove method rows — the method set is the official
  Magaya API list. Only change a `Status` cell or a computed count.
- Mark a method ✅ only when client + model/parser + resource/use-case + green
  test all exist. Otherwise leave 🟡. Never mark a 🚫 write method done.
- Recompute counts by recounting the emoji across every group table. Do not
  hand-adjust a number without recounting.

## Decision Gates

| Situation | Action |
| --- | --- |
| Method fully done (code + test) | Set its row to ✅, recount |
| Partially done / no test | Leave 🟡, stop |
| Write method (`Set*`/`Submit*`/`Delete*`/`Update*`/`Cancel*`/`Approve*`/`Rename*`) | Leave 🚫, stop |

## Execution Steps

1. Verify the method is truly done (see Hard Rules). If not, stop.
2. In the marked block, set that method's `Status` cell to ✅.
3. Recount across ALL group tables: `Done` = ✅ count, `Read, pending` = 🟡
   count, `Write` = 🚫 count, `Generic` = 🔧 count. `Total API methods` stays 59.
4. Update the summary table with the new counts.
5. Update the line `**Read coverage: X / 34 read methods (~Y%)**`: `X` = ✅
   count minus 2 session methods (StartSession/EndSession); `Y` = round(X/34*100).
6. If the method unlocks a capability, update the high-level `## Status` table too.
7. Commit: `docs: mark <Method> as done in API coverage`.

## Output Contract

Report: the method flipped, the old→new summary counts, the new read-coverage
percentage, and the commit made.

## References

- `README.md` — `## API coverage` section (the data this skill maintains).
- Official method list: <https://dev.magaya.com/index.php/API>
