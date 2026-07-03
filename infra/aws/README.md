# AWS paper-only infrastructure

Templates define ECR, S3, CloudWatch Logs, ECS/Fargate placeholders, EventBridge Scheduler placeholders, SNS alerts, Secrets Manager references, and DynamoDB locks. Defaults keep `enable_paper_submission=false`. Review all Terraform plans before apply. CI must never run `terraform apply` or require AWS credentials.
