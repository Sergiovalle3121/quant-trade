# Paper-only deployment. Review before apply; nothing here enables live
# trading — the application enforces paper-only gates independently.

resource "aws_ecr_repository" "app" {
  name = var.project_name
}

resource "aws_s3_bucket" "artifacts" {
  bucket = var.artifact_bucket_name
}

# The kill-switch and heartbeat state live in this bucket: versioning gives
# an audit trail of who flipped what, encryption and a public-access block
# are table stakes.
resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    id     = "expire-old-artifacts"
    status = "Enabled"
    filter {
      prefix = "cloud/"
    }
    expiration {
      days = 180
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/quant-trade/${var.environment}"
  retention_in_days = 30
}

resource "aws_sns_topic" "alerts" {
  name = "${var.project_name}-${var.environment}-alerts"
}

resource "aws_sns_topic_subscription" "alert_email" {
  count     = var.alert_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# expires_at_epoch is a NUMBER attribute; the lock code writes it as N so
# TTL actually purges dead locks.
resource "aws_dynamodb_table" "locks" {
  name         = "${var.project_name}-locks"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "lock_name"

  attribute {
    name = "lock_name"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at_epoch"
    enabled        = true
  }
}
