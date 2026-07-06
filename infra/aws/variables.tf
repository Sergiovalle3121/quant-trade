variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "project_name" {
  type    = string
  default = "quant-trade"
}

variable "environment" {
  type    = string
  default = "paper"
}

# Image to run on the paper host, e.g. <account>.dkr.ecr.<region>.amazonaws.com/quant-trade:latest
variable "image_uri" {
  type = string
}

variable "artifact_bucket_name" {
  type = string
}

# Email that receives dead-man and job-failure alerts. The subscription must
# be confirmed once by the recipient after apply.
variable "alert_email" {
  type    = string
  default = ""
}

variable "alpaca_paper_secret_name" {
  type    = string
  default = "quant-trade/paper/alpaca"
}

# Per the deployment plan: one always-on t3.small (~$15/mo on-demand) is the
# paper runtime; scale up only with evidence that it is insufficient.
variable "instance_type" {
  type    = string
  default = "t3.small"
}

# Heartbeat is considered dead after this many seconds without updates.
variable "heartbeat_stale_seconds" {
  type    = number
  default = 3600
}

variable "enable_paper_submission" {
  type    = bool
  default = false
}
