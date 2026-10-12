# Odoo 17 on Fargate, with its own Postgres 15. This database is not the portal
# Aurora cluster. The UI is public through its own load balancer; the database is
# reachable only from the Odoo task.

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "exec_channel" {
  statement {
    actions = [
      "ssmmessages:CreateControlChannel",
      "ssmmessages:CreateDataChannel",
      "ssmmessages:OpenControlChannel",
      "ssmmessages:OpenDataChannel",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role" "task" {
  name               = "${var.prefix}-odoo-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy" "task" {
  name   = "odoo-exec"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.exec_channel.json
}

resource "aws_security_group" "alb" {
  name        = "${var.prefix}-odoo-alb"
  description = "Public ingress to the Odoo load balancer"
  vpc_id      = var.vpc_id

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "${var.prefix}-odoo-alb" }
}

resource "aws_security_group" "task" {
  name        = "${var.prefix}-odoo"
  description = "Odoo task, port 8069 from its load balancer"
  vpc_id      = var.vpc_id

  ingress {
    description     = "Odoo from its ALB"
    from_port       = 8069
    to_port         = 8069
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "${var.prefix}-odoo" }
}

resource "aws_security_group" "db" {
  name        = "${var.prefix}-odoo-db"
  description = "Odoo Postgres, from the Odoo task only"
  vpc_id      = var.vpc_id

  ingress {
    description     = "Postgres from the Odoo task"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.task.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "${var.prefix}-odoo-db" }
}

resource "aws_db_subnet_group" "odoo" {
  name       = "${var.prefix}-odoo"
  subnet_ids = var.subnet_ids
  tags       = { Name = "${var.prefix}-odoo" }
}

# Odoo talks plain Postgres. RDS Postgres 15 turns SSL on by default, which the
# stock client does not use.
resource "aws_db_parameter_group" "odoo" {
  name   = "${var.prefix}-odoo-pg15"
  family = "postgres15"

  parameter {
    name  = "rds.force_ssl"
    value = "0"
  }
}

resource "aws_secretsmanager_secret" "db_password" {
  name        = "${var.prefix}/odoo/db-password"
  description = "Password for the Odoo RDS user. Not the portal Aurora password."
}

resource "aws_secretsmanager_secret_version" "db_password" {
  secret_id     = aws_secretsmanager_secret.db_password.id
  secret_string = var.odoo_db_password

  lifecycle {
    ignore_changes = [secret_string]
  }
}

resource "aws_iam_role_policy" "execution_read_db_password" {
  name = "odoo-db-password"
  role = var.execution_role_name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = [aws_secretsmanager_secret.db_password.arn]
    }]
  })
}

resource "aws_db_instance" "odoo" {
  identifier              = "${var.prefix}-odoo"
  engine                  = "postgres"
  engine_version          = "15"
  instance_class          = "db.t3.micro"
  allocated_storage       = 20
  storage_type            = "gp3"
  storage_encrypted       = true
  db_name                 = "odoo"
  username                = "odoo"
  password                = var.odoo_db_password
  db_subnet_group_name    = aws_db_subnet_group.odoo.name
  parameter_group_name    = aws_db_parameter_group.odoo.name
  vpc_security_group_ids  = [aws_security_group.db.id]
  publicly_accessible     = false
  multi_az                = false
  backup_retention_period = 1
  skip_final_snapshot     = true
  deletion_protection     = false

  lifecycle {
    ignore_changes = [password]
  }
}

resource "aws_cloudwatch_log_group" "odoo" {
  name              = "/ecs/${var.prefix}/odoo"
  retention_in_days = 30
}

resource "aws_ecs_cluster" "odoo" {
  name = "${var.prefix}-odoo"
}

resource "aws_ecs_task_definition" "odoo" {
  family                   = "${var.prefix}-odoo"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 1024
  memory                   = 2048
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name         = "odoo"
    image        = var.odoo_image
    essential    = true
    portMappings = [{ containerPort = 8069, protocol = "tcp" }]
    environment = [
      { name = "HOST", value = aws_db_instance.odoo.address },
      { name = "PORT", value = "5432" },
      { name = "USER", value = "odoo" },
    ]
    secrets = [{
      name      = "PASSWORD"
      valueFrom = aws_secretsmanager_secret.db_password.arn
    }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.odoo.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "odoo"
      }
    }
  }])
}

resource "aws_lb" "odoo" {
  name               = "${var.prefix}-odoo"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.subnet_ids
  idle_timeout       = 120
}

resource "aws_lb_target_group" "odoo" {
  name        = "${var.prefix}-odoo"
  port        = 8069
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/web/login"
    matcher             = "200"
    interval            = 30
    timeout             = 10
    healthy_threshold   = 2
    unhealthy_threshold = 10
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.odoo.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.odoo.arn
  }
}

resource "aws_ecs_service" "odoo" {
  name                   = "${var.prefix}-odoo"
  cluster                = aws_ecs_cluster.odoo.name
  task_definition        = aws_ecs_task_definition.odoo.arn
  desired_count          = 1
  launch_type            = "FARGATE"
  enable_execute_command = true

  # First boot installs Sales, Inventory, and Invoicing before it listens.
  health_check_grace_period_seconds = 1800

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [aws_security_group.task.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.odoo.arn
    container_name   = "odoo"
    container_port   = 8069
  }

  depends_on = [aws_lb_listener.http, aws_db_instance.odoo]
}
