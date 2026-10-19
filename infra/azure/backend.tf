# Remote state: Storage Account + container (created once by infra/azure/bootstrap).
# A blob lease does locking — no separate lock-table resource, unlike the S3+DynamoDB
# backend.
#   terraform init -backend-config=envs/staging.backend.tfbackend
# See docs/deploy-azure.md.
terraform {
  backend "azurerm" {
    # resource_group_name / storage_account_name / container_name / key come from the
    # -backend-config file.
  }
}
