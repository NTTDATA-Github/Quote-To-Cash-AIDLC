output "topic_arn" {
  value = aws_sns_topic.domain_events.arn
}

output "work_queue_urls" {
  value = { for k, q in aws_sqs_queue.work : k => q.url }
}

output "work_queue_arns" {
  value = [for q in aws_sqs_queue.work : q.arn]
}

output "dlq_urls" {
  value = { for k, q in aws_sqs_queue.dlq : k => q.url }
}

output "dlq_arns" {
  value = [for q in aws_sqs_queue.dlq : q.arn]
}
