# AWS paper-only infrastructure

One always-on **EC2 t3.small** (~$15/mo on-demand) is the paper runtime, plus
the supporting pieces: ECR, a hardened S3 artifacts bucket (versioned,
encrypted, public access blocked, lifecycle expiry), CloudWatch logs, the
DynamoDB lock table (numeric `expires_at_epoch` TTL that matches the lock
code), an SNS alert topic with optional email subscription, and two alarms:

- **Dead-man switch**: `heartbeat_age_seconds` in `QuantTrade/CloudPaper`
  with `treat_missing_data = breaching` — a process that stops emitting
  heartbeats trips the alarm; so does a stale one.
- **Job failures**: any `job_failure` metric > 0.

Nothing here enables live trading; the application enforces paper-only gates
independently of infrastructure.

## Deploy (manual, review-first)

```bash
cd infra/aws
cp terraform.tfvars.example terraform.tfvars   # edit values
terraform init
terraform plan     # REVIEW the plan
terraform apply
```

Then, from a workstation with credentials:

```bash
aws ecr get-login-password | docker login --username AWS --password-stdin <ecr>
docker build -t <ecr>/quant-trade:paper . && docker push <ecr>/quant-trade:paper
```

The instance boots running the safe default command (health check). Switch it
to the paper loop via SSM Session Manager after reviewing configs:

```bash
docker rm -f quant-trade
docker run -d --name quant-trade --restart unless-stopped \
  --log-driver awslogs --log-opt awslogs-region=<region> \
  --log-opt awslogs-group=/quant-trade/paper \
  <ecr>/quant-trade:paper \
  paper loop --config /app/configs/paper/loop_crypto_daily.yaml \
  --max-cycles 0 --interval-seconds 3600
```

Confirm the SNS email subscription once after apply, or alerts go nowhere.

## Boundaries

- CI validates Terraform (`fmt` + `validate`) but never plans or applies:
  no AWS credentials live in CI.
- `enable_paper_submission` defaults to false and only affects application
  config; flipping it does not create live-trading capability.
- Review every plan before apply.
