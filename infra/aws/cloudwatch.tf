# Dead-man switch: the loop/jobs emit heartbeat_age_seconds via EMF into
# QuantTrade/CloudPaper. Missing data BREACHES — a dead process that stops
# emitting is exactly the condition this alarm exists to catch.

resource "aws_cloudwatch_metric_alarm" "heartbeat_dead_man" {
  alarm_name          = "${var.project_name}-${var.environment}-heartbeat-dead"
  alarm_description   = "Paper runtime heartbeat is stale or absent"
  namespace           = "QuantTrade/CloudPaper"
  metric_name         = "heartbeat_age_seconds"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 3
  threshold           = var.heartbeat_stale_seconds
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  dimensions = {
    job = "heartbeat"
  }
}

resource "aws_cloudwatch_metric_alarm" "job_failures" {
  alarm_name          = "${var.project_name}-${var.environment}-job-failure"
  alarm_description   = "A cloud job reported failure"
  namespace           = "QuantTrade/CloudPaper"
  metric_name         = "job_failure"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
