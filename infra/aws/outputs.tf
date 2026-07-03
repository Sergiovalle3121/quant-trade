output "ecr_repository_url" { value = aws_ecr_repository.app.repository_url }
output "artifact_bucket" { value = aws_s3_bucket.artifacts.bucket }
output "log_group" { value = aws_cloudwatch_log_group.app.name }
