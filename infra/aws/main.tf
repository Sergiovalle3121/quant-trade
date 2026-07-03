resource "aws_ecr_repository" "app" { name = var.project_name }
resource "aws_s3_bucket" "artifacts" { bucket = var.artifact_bucket_name }
resource "aws_cloudwatch_log_group" "app" { name = "/ecs/${var.project_name}" retention_in_days = 30 }
resource "aws_ecs_cluster" "app" { name = var.project_name }
resource "aws_sns_topic" "alerts" { name = "${var.project_name}-paper-alerts" }
resource "aws_dynamodb_table" "locks" { name = "${var.project_name}-locks" billing_mode = "PAY_PER_REQUEST" hash_key = "lock_name" attribute { name = "lock_name" type = "S" } ttl { attribute_name = "expires_at_epoch" enabled = true } }
# ECS task/scheduler/IAM templates are intentionally minimal and paper-only; expand after review.
