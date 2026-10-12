# SNS FIFO topic -> SQS FIFO queues (+ DLQs). Runs on BOTH floci and AWS. Mirrors
# scripts/messaging_bootstrap.py 1:1 (that script is the source of truth the worker
# consumes against).

resource "aws_sns_topic" "domain_events" {
  name                        = var.topic_name
  fifo_topic                  = true
  content_based_deduplication = false
}

resource "aws_sqs_queue" "dlq" {
  for_each                    = var.queue_filters
  name                        = replace(each.key, ".fifo", "-dlq.fifo")
  fifo_queue                  = true
  content_based_deduplication = false
  message_retention_seconds   = 1209600 # 14 days
}

resource "aws_sqs_queue" "work" {
  for_each                    = var.queue_filters
  name                        = each.key
  fifo_queue                  = true
  content_based_deduplication = false

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq[each.key].arn
    maxReceiveCount     = var.max_receive_count
  })
}

resource "aws_sqs_queue_policy" "allow_sns" {
  for_each  = var.queue_filters
  queue_url = aws_sqs_queue.work[each.key].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowSNSPublish"
      Effect    = "Allow"
      Principal = { Service = "sns.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.work[each.key].arn
      Condition = {
        ArnEquals = { "aws:SourceArn" = aws_sns_topic.domain_events.arn }
      }
    }]
  })
}

resource "aws_sns_topic_subscription" "to_queue" {
  for_each             = var.queue_filters
  topic_arn            = aws_sns_topic.domain_events.arn
  protocol             = "sqs"
  endpoint             = aws_sqs_queue.work[each.key].arn
  raw_message_delivery = true

  filter_policy       = each.value == null ? null : jsonencode({ eventType = each.value })
  filter_policy_scope = each.value == null ? null : "MessageAttributes"
}
