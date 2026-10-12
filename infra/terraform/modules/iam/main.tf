# IAM task roles (least-privilege) + optional GitHub Actions OIDC deploy role.

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "task_execution" {
  name               = "${var.prefix}-task-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "task_execution" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# ECS Exec channel (so `aws ecs execute-command` can shell into a task for debugging).
data "aws_iam_policy_document" "exec_channel" {
  statement {
    actions = [
      "ssmmessages:CreateControlChannel",
      "ssmmessages:CreateDataChannel",
      "ssmmessages:OpenControlChannel",
      "ssmmessages:OpenDataChannel",
    ]
    resources = ["*"] # SSM messaging channels are not resource-scopable.
  }
}

# api: read/write project secrets (inbound webhook signing keys).
data "aws_iam_policy_document" "api_task" {
  source_policy_documents = [data.aws_iam_policy_document.exec_channel.json]

  statement {
    sid       = "ReadWriteProjectSecrets"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:CreateSecret", "secretsmanager:PutSecretValue"]
    resources = [var.secret_arn_glob]
  }
}

resource "aws_iam_role" "api_task" {
  name               = "${var.prefix}-api-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy" "api_task" {
  name   = "api-task"
  role   = aws_iam_role.api_task.id
  policy = data.aws_iam_policy_document.api_task.json
}

# worker: consume SQS, publish SNS (outbox relay), read/write project secrets.
data "aws_iam_policy_document" "worker_task" {
  source_policy_documents = [data.aws_iam_policy_document.exec_channel.json]

  statement {
    sid       = "ConsumeQueues"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:GetQueueUrl", "sqs:ChangeMessageVisibility"]
    resources = concat(var.work_queue_arns, var.dlq_arns)
  }
  statement {
    sid       = "PublishDomainEvents"
    actions   = ["sns:Publish"]
    resources = [var.topic_arn]
  }
  statement {
    sid       = "ReadWriteProjectSecrets"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:CreateSecret", "secretsmanager:PutSecretValue"]
    resources = [var.secret_arn_glob]
  }
}

resource "aws_iam_role" "worker_task" {
  name               = "${var.prefix}-worker-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy" "worker_task" {
  name   = "worker-task"
  role   = aws_iam_role.worker_task.id
  policy = data.aws_iam_policy_document.worker_task.json
}

# --- GitHub Actions OIDC deploy role (optional) ------------------------------
locals {
  make_oidc = var.github_oidc_repo != "" ? 1 : 0
}

resource "aws_iam_openid_connect_provider" "github" {
  count           = local.make_oidc
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

data "aws_iam_policy_document" "github_assume" {
  count = local.make_oidc
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github[0].arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_oidc_repo}:*"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  count              = local.make_oidc
  name               = "${var.prefix}-github-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_assume[0].json
}

resource "aws_iam_role_policy_attachment" "github_deploy" {
  for_each = local.make_oidc == 1 ? toset([
    "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser",
    "arn:aws:iam::aws:policy/AmazonECS_FullAccess",
  ]) : toset([])
  role       = aws_iam_role.github_deploy[0].name
  policy_arn = each.value
}
