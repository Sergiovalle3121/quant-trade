# Mining Telemetry (Read-Only)

`mining/telemetry.py` reads rig state and reconciles observed payouts. It
**controls nothing**. Three safety constants are hard-wired off and asserted by
tests:

```python
AUTHORIZED_TO_START_MINER = False
HARDWARE_CONTROL_ENABLED  = False
WALLET_SIGNING_ENABLED    = False
```

`MINING_HARDWARE_CONTROL: DISABLED`. Wallets are watch-only.

## Inventory & telemetry

- `RigInventoryItem` — rig id, **redacted** serial (last 4 chars via
  `redact_serial`), facility, rack, algorithm, rated hashrate/watts.
- `TelemetrySample` — hashrate, power, temperature, fan RPM, reject rate, uptime,
  last-seen, and staleness.

## Adapters (read-only by contract)

`TelemetryAdapter` is a `Protocol` with a single `read(rig_id)` verb — **no**
`start`/`stop`/`restart`/`overclock`/`reboot`/`set_frequency` methods (a test
asserts these names are absent). A future CGMiner/Braiins integration must
implement only `read`. `FakeTelemetryAdapter` and JSON/CSV importers cover
offline use; tests never touch the network.

## Local alerts

`evaluate_alerts` produces (never acts on) alerts for: over-temperature,
hashrate drop vs rated, power anomaly, stale telemetry, reject-rate spike,
negative economics, and payout mismatch.

## Watch-only payout reconciliation

`reconcile_payouts(expected, observed)` compares expected coin production against
observed **watch-only** wallet payouts and flags drift beyond tolerance. It only
compares numbers — `wallet_is_watch_only` is always true and no code path signs
or moves funds.

## Daily operating ledger

`DailyOperatingLedger` accumulates per-rig daily entries (energy, electricity
cost, coin mined, payout, net USD) and exports JSON for the operations record.

## Status

`MINING_TELEMETRY: READY` (read-only). The interfaces are in place for real
telemetry import and reconciliation; connecting them to physical devices is out
of scope and disabled by design.
