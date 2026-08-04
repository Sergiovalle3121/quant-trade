# Mining retirement record

The mining research routes were retired in August 2026, across two pull
requests: stages 0–2 (the standalone `mining/` package) and stages 3–5
(the V9 route, the V8 hashrate marketplace, and `cloud_rental/` with the
opportunity board's mining half). This document records what left, what
deliberately stayed, and why — so the retirement is legible without
archaeology.

## What was retired

| Piece | Size | Where it went |
|---|---|---|
| `mining/` package (hardware economics, telemetry, tariffs) | 2,514 lines | deleted, stages 1–2 |
| `cloud_rental/` (AWS/Alibaba rented-compute evaluation) | 2,276 lines | deleted, stage 5 |
| `v9/mining_{units,cashflow,evidence,shadow}.py` | 1,919 lines | deleted, stage 3 |
| `v8/hashrate_{market,cashflow}.py` | 912 lines | deleted, stage 4 |
| `opportunities/mining_scan.py` + board mining half | 276 lines + surgery | deleted, stage 5 |
| Mining CLI groups and commands | `mining`, `cloud-rental`, `opportunities scan-mining`, `v8 mining-scan`, `v9 mining-units`, `v9 mining-shadow-status` | removed |
| Committed `MINING_*` artifacts in v7/v8/v9 (and `UNIT_CONVERSION_AUDIT`) | 10 files | deleted; generators regenerated |
| ~250 mining tests | | deleted or surgically reduced, census-verified |

Everything deleted survives in git history; the last commit carrying all of it
is `5474c97`.

## What deliberately stayed, and why

- **The sealed V9 pre-registration is untouched.** `mining_gates` and the
  E9/E10 errata are part of what was registered on 2026-07-28 at commit
  `3818c2d1`; `freeze_hash()` still evaluates to `c62076bd…`, the value
  stamped in every V9 artifact and cited in the V9 reports. Retiring a route
  does not un-declare it — the registration is history, and this file is the
  documentation that lives outside the sealed content. The errata record real
  defects (E9 was a factor-1,000 unit error in hashrate pricing); retiring the
  module does not make them not have happened.
- **`v9/safety.py` keeps its mining prohibitions.** They are negative
  assertions — "no verb named `buy_hashrate` exists in this repository" — that
  remain true and cost nothing, and the same lists guard `WALLET_SIGNING` and
  `LIVE_ORDER_SUBMISSION`, which matter for the crypto work ahead. The same
  applies to `test_v8_safety`'s forbidden-name scan, the scorecard's
  `MINING_HARDWARE_CONTROL: DISABLED` line, and the `miner_execution` /
  `hardware_control_enabled` keys in `evidence/safety_posture.py`.
- **v5/v6 artifacts are frozen history.** CI never regenerated them, and they
  are the committed output of sprints that did evaluate mining. Editing or
  deleting them would be rewriting the record; their mining rows stay, and no
  live code reads them any more.
- **Historical reports and worklogs are untouched** — including
  `RENTED_MINING_REALITY_V9_REPORT.md` and
  `CLOUD_RENTAL_V4_IMPLEMENTATION_REPORT.md`, which are minutes of work that
  happened. Only living documentation of deleted code was removed
  (`CLOUD_RENTAL_FEASIBILITY.md`, the `MINING_*.md` how-tos).
- **The board's architecture outlived its mining half.** One common unit (net
  return on committed capital, 30 days), a byte-verified cash baseline as the
  ranking floor, lineage-hashed inputs, fail-closed on clock mismatch. The
  `kind` axis is open for the next candidate type; what was removed is one
  scorer, not the machine.
- **`carry/` was never touched.** Verified before and after: zero mining
  imports in either direction. It is the substrate for the low/mid-cap crypto
  data work.

## Patterns extracted before deletion

`docs/COLLECTOR_INTEGRITY_PATTERN.md` preserves the anti-forgery design of the
shadow collector (persisted-clock elapsed time, hash-chained journal, gaps as
first-class records, policy frozen by hash), plus the freshness rule from V4
defect E. A collector for illiquid tokens will need both.

## Why it was retired

The route's own artifacts said it best: every mining cell was
`POLICY_BLOCKED` or blocked on evidence that could not be captured
(marketplace unreachable, no pool records, no delivery history), the V7 board
ranked every mining candidate below cash, and the V9 sprint capped the route
at `SHADOW_MARKET_ONLY` with its budget underivable. Nothing in the retirement
contradicts a measured result, because there never was a measured mining
result to contradict.
