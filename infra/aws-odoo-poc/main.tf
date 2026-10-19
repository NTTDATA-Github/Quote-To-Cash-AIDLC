# Minimum viable Odoo on AWS: one EC2 box running Odoo + its own Postgres as two
# Docker containers (the same odoo/odoo-db pair as the repo's docker-compose.yml).
# No RDS, no ALB, no ECS, no ECR, no Secrets Manager, no custom VPC. Not the staging
# path (infra/terraform) -- this is a throwaway POC: one instance, no HA, no backups.

data "aws_vpc" "default" {
  default = true
}

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
}

resource "aws_security_group" "odoo" {
  name        = "odoo-poc"
  description = "Odoo POC: 8069 (and 22 if you want SSH) from allowed_cidr"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "Odoo"
    from_port   = 8069
    to_port     = 8069
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
  }

  ingress {
    description = "Odoo over HTTPS (self-signed, via nginx)"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
  }

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "odoo" {
  ami           = data.aws_ami.al2023.id
  instance_type = var.instance_type
  # No subnet_id: let EC2 pick a default-VPC AZ that actually has t3.small
  # capacity, instead of hardcoding one that might not (bit us on us-east-1e).
  vpc_security_group_ids      = [aws_security_group.odoo.id]
  key_name                    = var.key_name
  associate_public_ip_address = true

  user_data = templatefile("${path.module}/user_data.sh.tpl", {
    odoo_boot_sh = file("${path.module}/../../scripts/odoo-boot.sh")
  })

  # Default AL2023 root volume (8GB) isn't enough to pull odoo:17 + postgres:15 --
  # filled the disk mid-pull and killed cloud-init. 20GB gives headroom.
  root_block_device {
    volume_size = 20
    volume_type = "gp3"
  }

  tags = {
    Name = "odoo-poc"
  }
}
