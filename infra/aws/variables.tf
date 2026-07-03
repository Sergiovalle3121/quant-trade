variable "aws_region" { type = string default = "us-east-1" }
variable "project_name" { type = string default = "quant-trade" }
variable "environment" { type = string default = "paper" }
variable "image_uri" { type = string }
variable "schedule_expression" { type = string default = "rate(1 day)" }
variable "artifact_bucket_name" { type = string }
variable "alert_email" { type = string default = "" }
variable "alpaca_paper_secret_name" { type = string default = "quant-trade/paper/alpaca" }
variable "enable_paper_submission" { type = bool default = false }
