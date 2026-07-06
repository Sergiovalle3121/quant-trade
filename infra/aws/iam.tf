# Least-privilege instance role for the paper host: artifacts bucket, the
# one Alpaca Paper secret, CloudWatch logs/metrics, the lock table, and ECR
# pulls. No broad wildcards.

data "aws_caller_identity" "current" {}

resource "aws_iam_role" "paper_host" {
  name = "${var.project_name}-${var.environment}-host"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "paper_host" {
  name = "${var.project_name}-${var.environment}-host"
  role = aws_iam_role.paper_host.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ArtifactBucket"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:DeleteObject"]
        Resource = [aws_s3_bucket.artifacts.arn, "${aws_s3_bucket.artifacts.arn}/*"]
      },
      {
        Sid    = "AlpacaPaperSecret"
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = [
          "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:${var.alpaca_paper_secret_name}*"
        ]
      },
      {
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
        Resource = ["${aws_cloudwatch_log_group.app.arn}:*"]
      },
      {
        Sid      = "Metrics"
        Effect   = "Allow"
        Action   = ["cloudwatch:PutMetricData"]
        Resource = ["*"]
        Condition = {
          StringEquals = { "cloudwatch:namespace" = "QuantTrade/CloudPaper" }
        }
      },
      {
        Sid    = "LockTable"
        Effect = "Allow"
        Action = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:DeleteItem"]
        Resource = [aws_dynamodb_table.locks.arn]
      },
      {
        Sid    = "EcrPull"
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer"
        ]
        Resource = ["*"]
      },
      {
        Sid      = "AlertPublish"
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = [aws_sns_topic.alerts.arn]
      }
    ]
  })
}

resource "aws_iam_instance_profile" "paper_host" {
  name = "${var.project_name}-${var.environment}-host"
  role = aws_iam_role.paper_host.name
}
