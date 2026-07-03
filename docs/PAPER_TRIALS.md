# Phase 9 Paper Trial Governance

Phase 9 adds paper-only trial management for 30/60/90-day strategy trials. Paper trading is a rehearsal for process, monitoring, fills, and operational controls; it does not prove profitability and never approves real-money trading.

## Workflow

Daily records are collected from local/offline artifacts, compared with wide research expectation ranges, reviewed against a benchmark, and summarized in weekly, monthly, or final review packs. Missing evidence and missing human notes are treated conservatively.

## Weekly paper trial review checklist

1. Confirm CI green.
2. Confirm no active kill switch.
3. Confirm no critical incidents.
4. Review daily records.
5. Review drawdown.
6. Review benchmark comparison.
7. Review slippage/fill quality.
8. Review rejected orders.
9. Review operational reliability.
10. Review drift warnings.
11. Record human notes.
12. Decide continue/pause/extend/reject.

## Safety

All outputs include paper-only warnings where relevant. Decision records force `real_money_approved=false`; real-money approval is explicitly out of scope.
