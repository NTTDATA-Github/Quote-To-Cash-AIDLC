# One-time bootstrap: creates the S3 bucket + DynamoDB table that hold Terraform remote
# state + locks for the main config. Run ONCE per account, with a LOCAL state file (this
# config has no remote backend — it's the chicken that lays the egg):
#
#   cd infra/terraform/bootstrap
#   terraform init
#   terraform apply
#
# Then init the main config against it (see docs/deploy-aws.md):
#   cd ..
#   terraform init -backend-config=envs/staging.s3.tfbackend
#
# Keep this bootstrap state file (terraform.tfstate) in the repo-ignored .local area or a
# password manager — it is tiny and rarely changes.

terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = "order-to-cash-connector"
      ManagedBy = "terraform-bootstrap"
    }
  }
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "state_bucket" {
  description = "Globally-unique S3 bucket name for Terraform state."
  type        = string
}

variable "lock_table" {
  description = "DynamoDB table name for state locks."
  type        = string
  default     = "o2c-tf-locks"
}

resource "aws_s3_bucket" "state" {
  bucket = var.state_bucket
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_dynamodb_table" "locks" {
  name         = var.lock_table
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"
  attribute {
    name = "LockID"
    type = "S"
  }
}

output "state_bucket" {
  value = aws_s3_bucket.state.id
}

output "lock_table" {
  value = aws_dynamodb_table.locks.name
}
