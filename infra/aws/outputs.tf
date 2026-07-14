output "ecr_repository_url" {
  value = aws_ecr_repository.app.repository_url
}

output "artifact_bucket" {
  value = aws_s3_bucket.artifacts.bucket
}

output "log_group" {
  value = aws_cloudwatch_log_group.app.name
}

output "paper_host_instance_id" {
  value = aws_instance.paper_host.id
}

output "alerts_topic_arn" {
  value = aws_sns_topic.alerts.arn
}

output "lock_table" {
  value = aws_dynamodb_table.locks.name
}

output "github_actions_ecr_push_role_arn" {
  value = aws_iam_role.github_actions_ecr_push.arn
}
