# CloudWatch log groups for the api + worker tasks. The app emits structured JSON to
# stdout; awslogs ships it here.

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.prefix}/api"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/${var.prefix}/worker"
  retention_in_days = 30
}
