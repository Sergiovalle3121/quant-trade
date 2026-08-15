# Quant Research Auditor: private pilot playbook

## Objective

Validate whether an independent research team will pay to find causal,
provenance, execution-cost, benchmark, and trial-governance defects before
money is allocated. A pilot validates demand for an audit; it does not validate
the customer's strategy, predict profit, provide investment advice, or permit
order execution.

## Initial customer profile

Prioritize teams that already have research artifacts but lack independent
review:

- independent quantitative researchers and consultants;
- small proprietary trading or digital-asset research teams;
- data/research vendors that need reproducible evidence for clients;
- engineering teams maintaining an internal backtest platform.

Do not target people seeking signals, guaranteed returns, managed accounts,
custody, pooling, copy trading, or a route around exchange controls.

## Pilot offer

The customer supplies a bounded BYOD package: dataset extract, manifest,
results, execution/cost assumptions, benchmark results, and trial ledger. The
operator runs `quant-trade audit` locally and returns:

- content hashes for every accepted input;
- a tri-state `PASS`, `NO_GO`, or `INSUFFICIENT_EVIDENCE` research verdict;
- check-level findings in deterministic JSON;
- an escaped standalone HTML report;
- a 30-minute findings review and a short remediation list.

`PASS` means only that the MVP's declared evidence checks passed. Every bundle
sets `expected_profit_established=false`,
`external_action_authorized=false`, and `real_money_authorized=false`.

## Security and scope for the first three pilots

- Run locally without network access during the audit.
- Never execute customer code, notebooks, formulas, binaries, or macros.
- Accept only the documented bounded CSV/JSON/JSONL dataset formats and JSON
  evidence.
- Agree in writing which files may be retained and delete working copies after
  delivery under that agreement.
- Do not upload, redistribute, or train on customer market data.
- Do not accept credentials, API keys, account exports, personal data, or
  production order endpoints.
- Use a fresh output directory for every run; never overwrite an audit bundle.

The repository currently has no root license, customer terms, privacy notice,
data-processing agreement, or professional-liability review. Resolve those
items before a public self-service launch. Private pilots require an explicit
written scope and retention agreement; this playbook is not legal advice.

## Thirty-day validation sequence

### Days 1–5: make the demo repeatable

1. Run the clean and contaminated fixtures from a clean checkout.
2. Confirm the clean package is `PASS` and the contaminated package is
   `NO_GO` without editing either package.
3. Record setup time, audit runtime, report digest, and every manual step.
4. Prepare a two-minute demo showing one look-ahead, one same-bar, and one
   byte-binding failure.

### Days 6–12: discovery before selling

Interview ten people in the initial customer profile. Ask about the last
research error that reached review, how it was detected, its cost, current
review time, who approves tooling, and what evidence a purchase would require.
Do not pitch returns. Record answers, not optimistic impressions.

### Days 13–23: three bounded pilots

Offer exactly the documented audit package. Quote each pilot manually only
after seeing scope; record the quote, acceptance or rejection, time spent,
findings, remediation outcome, and whether the customer asks for a repeat.
Do not build billing, multi-tenancy, hosted uploads, or arbitrary-code
sandboxes during these pilots.

### Days 24–30: decide from evidence

Continue only when all of these are true:

- at least three independent packages were completed;
- at least one customer actually paid, rather than only saying they would;
- at least two customers request a repeat, extension, or ongoing use;
- median operator time per package is low enough to leave a positive service
  margin at the prices customers accepted;
- no customer data escaped the agreed boundary;
- the audit found at least one material, actionable issue or verified a
  previously uncertain control in most pilots.

If these conditions fail, publish the evidence internally and change the
customer/problem before building more platform. Do not compensate by adding
trading signals or performance promises.

## Outreach message

> I built a local, no-code-execution audit for quantitative research packages.
> It checks whether results are bound to the supplied data, whether timestamps
> and execution are causal, and whether costs, benchmarks, and trial evidence
> are present. It does not score future returns or connect to an exchange. I am
> looking for three private research teams willing to test a bounded package
> and review the findings. Would a 20-minute call about your current research
> review process be useful?

## Metrics ledger

For each conversation or pilot, record:

- customer profile and concrete research-review problem;
- current review workflow and time spent;
- quoted and accepted price, separately;
- package size and audit/operator runtime;
- findings by severity and whether they were accepted;
- repeat-use request and purchasing authority;
- security, format, and missing-check objections.

Revenue is recognized only when collected. Pipeline, verbal interest, report
count, backtest return, and hypothetical willingness to pay are not revenue.
