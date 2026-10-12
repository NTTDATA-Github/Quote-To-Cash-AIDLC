# AWS provider. When use_floci=true, point every service at the floci endpoint and use
# dummy credentials — the same boto3 app code and the same Terraform run locally and in
# AWS, only the endpoints/creds differ (mirrors the app's AWS_ENDPOINT_URL approach).
provider "aws" {
  region = var.region

  # floci-only knobs. In real AWS these are null/false and ignored.
  access_key                  = var.use_floci ? "test" : null
  secret_key                  = var.use_floci ? "test" : null
  skip_credentials_validation = var.use_floci
  skip_requester_account_id   = var.use_floci
  skip_metadata_api_check     = var.use_floci
  s3_use_path_style           = var.use_floci

  dynamic "endpoints" {
    for_each = var.use_floci ? [1] : []
    content {
      sns            = var.floci_endpoint
      sqs            = var.floci_endpoint
      secretsmanager = var.floci_endpoint
      cognitoidp     = var.floci_endpoint
      sts            = var.floci_endpoint
    }
  }

  default_tags {
    tags = {
      Project     = "order-to-cash-connector"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
