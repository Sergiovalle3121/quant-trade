#!/usr/bin/env bash
set -euo pipefail
quant-trade cloud validate-config --config configs/cloud/local_dry_run.yaml
quant-trade cloud run-job --config configs/cloud/local_dry_run.yaml --job health_check
quant-trade cloud run-job --config configs/cloud/local_dry_run.yaml --job broker_plan
