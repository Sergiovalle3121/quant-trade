# Cloud deployment plan — paper loop, 24/7, cheapest that works

Status: **plan only. Nothing in this document has been applied; no AWS
resource exists because of it.** `terraform apply` stays manual, per the
phase-7 rules in AGENTS.md.

Everything below builds on infrastructure files that already exist under
`infra/aws/` (EC2 host, IAM, ECR, S3 artifacts bucket, CloudWatch dead-man
alarm, GitHub OIDC). This plan chooses sizes, walks the secret path
end-to-end, and writes the runbook. It also records *why* the cloud is the
place the operational verification happens: the development machine is
Windows with an Application Control policy that blocks pandas, so the paper
loop cannot run there at all. Linux is not just the deploy target; it is the
only place the system can be proven.

## 1. Shape and cost

The workload is small on purpose: one process, a 240-second idempotent cycle
(`configs/paper/loop_ew_quarterly_prod.yaml` — cycles heartbeat; the strategy
itself rebalances quarterly, so almost every cycle is a no-op "marked"
cycle). Peak memory observed for one cycle locally was under 200 MB.

**Recommended: `t4g.micro` (1 GiB, ARM) + 8 GiB gp3.**

| Piece | Monthly (us-east-1, on-demand) |
|---|---|
| EC2 `t4g.micro` | ~$6.13 |
| EBS 8 GiB gp3 | ~$0.64 |
| Secrets Manager (1 secret) | $0.40 |
| CloudWatch (2 alarms, logs, EMF metrics) | < $1 |
| S3 (kill switch + heartbeat + artifacts) | pennies |
| **Total** | **≈ $8/month** |

Notes on the choice:

- The committed default (`infra/aws/variables.tf`, `t3.small`) is ~$15/mo and
  over-provisioned. `t4g.nano` (~$3.06) would likely work with swap enabled
  but leaves no headroom for yfinance's worst days; the extra $3/mo buys not
  being paged for OOM. Set `instance_type = "t4g.micro"` in
  `terraform.tfvars`.
- ARM requires the image built for `linux/arm64`
  (`docker buildx build --platform linux/arm64`); the base
  `python:3.11-slim` is multi-arch, so this is a build flag, not a code
  change. If that is friction, `t3a.micro` (x86, ~$6.80/mo) needs no build
  change.
- **Lambda + EventBridge would cost ≈ $0** (21,600 invocations/month of ~20 s
  at 512 MB sits inside the free tier) and was seriously considered. It is
  not chosen because `state_dir` in `live/loop.py` is a local filesystem path:
  Lambda would need an S3/EFS state layer that does not exist, and writing
  glue code to save $8/mo is exactly the kind of new surface this phase does
  not add. If the bot earns the right to stay running for a year, revisit.
- Spot is not appropriate: a stateful 24/7 singleton that must not run twice
  concurrently gains nothing from a 70% discount on being interrupted.

## 2. Secrets — how credentials move without being printed or stored in the repo

The only secret the loop needs is the Alpaca **paper** key pair. The path:

1. **Origin**: created in the Alpaca dashboard for the paper account
   (`PA3BXMVUX4E6`). They exist in exactly two places ever: Alpaca's side,
   and AWS Secrets Manager.
2. **Storage**: one Secrets Manager secret (name = `alpaca_paper_secret_name`
   in `terraform.tfvars`), a JSON object with keys `ALPACA_PAPER_API_KEY`
   and `ALPACA_PAPER_SECRET_KEY`. Created by the operator with
   `aws secretsmanager create-secret` from a shell with history disabled
   (`HISTCONTROL=ignorespace`, leading space), or via the console.
3. **Access**: the instance role (`infra/aws/iam.tf:34-36`) can read exactly
   that one secret ARN and nothing else. No human credential lives on the
   host; the instance has no SSH key and no inbound ports — access is SSM
   Session Manager only (`infra/aws/ec2.tf`).
4. **Delivery into the process**, without appearing in shell history, `ps`,
   or docker inspect output on the way:

   ```bash
   # on the host, via SSM session; tmpfs so it never touches disk
   sudo install -m 700 -d /dev/shm/qt
   aws secretsmanager get-secret-value \
     --secret-id "$SECRET_NAME" --query SecretString --output text \
     | python3 -c 'import json,sys;[print(f"{k}={v}") for k,v in json.load(sys.stdin).items()]' \
     > /dev/shm/qt/env
   docker run -d --name quant-trade --restart unless-stopped \
     --env-file /dev/shm/qt/env \
     ... (image, logging flags as in ec2.tf user_data) ... \
     quant-trade paper loop \
       --config /app/configs/paper/loop_ew_quarterly_prod.yaml \
       --max-cycles 0 --interval-seconds 240
   rm -rf /dev/shm/qt
   ```

   `--env-file` keeps the values out of the command line (so out of shell
   history and `ps`); the tmpfs file is deleted immediately after start.
   Residual exposure: `docker inspect` on the host shows container env to
   root — acceptable on a single-purpose host with no other users.
5. **What never happens**: keys in the repo, in userdata, in terraform state,
   in CloudWatch logs (the app never logs env), or in `.env` on the host.
   The local `.env` on the Windows machine is for local runs only and its
   Alpaca fields can stay empty forever as far as the cloud is concerned.

## 3. Kill switch — how you stop it from anywhere

Two independent layers, both already implemented in the app:

1. **Remote kill switch (S3)**: the loop checks `kill_switch_uri` every
   cycle (`live/loop.py:_kill_switch_active`) and **fails closed** — an
   unreadable switch halts the loop, a missing file means "not active".
   After `terraform apply`, set the real bucket in the prod config
   (replacing `s3://REPLACE_BUCKET/...`). To kill from any machine with AWS
   credentials:

   ```bash
   aws s3 cp - s3://<artifacts-bucket>/cloud/kill_switch.json <<'JSON'
   {"active": true, "reason": "operator kill: <why>"}
   JSON
   ```

   The loop halts within one cycle (≤ 240 s), writes the halt to
   `events.jsonl`, and the heartbeat goes stale → dead-man alarm fires →
   SNS email. Deleting the file (or `"active": false`) re-arms; the loop
   does not auto-restart after a halt — restarting is an operator action.
2. **Hard stop (instance)**: `aws ec2 stop-instances` — for when you want
   the machine dead, not just the loop. The dead-man alarm fires here too.

## 4. Runbook

### Start (first time)

1. `cd infra/aws && cp terraform.tfvars.example terraform.tfvars` — set
   `instance_type = "t4g.micro"`, bucket name, alert email, secret name.
2. `terraform init && terraform plan` — **read the plan** — `terraform apply`.
3. Confirm the SNS subscription email.
4. Create the secret (§2.2). Build and push the image
   (`docker buildx build --platform linux/arm64 -t <ecr>:<tag> . && docker push`).
5. Edit `configs/paper/loop_ew_quarterly_prod.yaml`: replace both
   `s3://REPLACE_BUCKET/...` URIs with the bucket from `terraform output`.
   Commit that change — the config is not a secret.
6. SSM into the host, start the loop container (§2.4).
7. Verify alive (below). Note the start time: the first canary-relevant
   window starts now, not at deploy.

### Am I alive?

- **CloudWatch**: `heartbeat_age_seconds` in namespace `QuantTrade/CloudPaper`
  updating every ~240 s; dead-man alarm `OK`. This is the authoritative
  signal — silence trips it (`treat_missing_data = breaching`).
- **S3**: `aws s3 cp s3://<bucket>/cloud/heartbeats/ew_quarterly_prod.json -`
  → `last_update_utc` fresh, `status: "running"`, equity sane.
- **Host** (SSM): `docker logs --tail 20 quant-trade` → one JSON summary per
  cycle, `action: "marked"` on non-rebalance days.

### Market close, weekends, holidays

Nothing special: cycles are idempotent no-ops when no new daily bar exists
(the config header documents this; the observed off-hours cycle output is
`action: "marked", orders: 0`). The heartbeat keeps beating through
weekends — a quiet market and a dead process look completely different to
the alarm, which is the point of heartbeating on cycles rather than trades.
Expect orders only on quarterly rebalance days, ~4 times a year, shortly
after a new daily bar appears.

### Emergency stop

§3.1 (S3 kill switch) from anywhere; §3.2 if the host itself must die.

### It fell over — recovery

1. The alarm email says heartbeat went stale. SSM in.
2. `docker ps -a` — container restarting? `docker logs quant-trade` for the
   last cycle's error. Crash-loops restart via `--restart unless-stopped`;
   a *halt* (kill switch, drawdown breaker) does **not** self-restart, by
   design — read `state/paper_loop/<session>/events.jsonl` for the reason.
3. State is on EBS and the loop is resume-safe (`loop_state.json`,
   `latest_state.json`); restarting the container resumes the session.
   Never hand-edit state files.
4. If the instance is gone: `terraform apply` recreates it; state on the
   EBS volume is lost with the instance unless you snapshot — for a paper
   session whose value is the *evidence trail*, snapshot before terminating,
   or accept restarting the session window.

### What the first cloud session must produce (the Block-3 debt)

The 24h+ run, the loop-vs-Alpaca reconciliation, and the real cost capture
could not run on the development machine (pandas blocked by local policy;
Alpaca credentials deliberately absent from it). They are the first cloud
session's job, in order: run ≥ 24 h; compare `latest_state.json` against
`broker account`/`positions` output; and record real fill data — with the
honest caveat that Alpaca paper fills are *Alpaca's simulation*, so
commissions (zero on Alpaca equities) become MEASURED but slippage remains
simulation-class evidence, not market-measured.

## 5. What was deliberately not done

- No resource created, no plan applied, no image pushed.
- No Lambda state layer (see §1).
- No change to application code: every mechanism named here
  (kill switch, heartbeat, EMF, resume) already exists and is tested.
