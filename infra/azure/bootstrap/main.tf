# One-time bootstrap: creates the Storage Account + container that hold Terraform remote
# state for the main config. Run ONCE per subscription, with a LOCAL state file:
#
#   cd infra/azure/bootstrap
#   terraform init
#   terraform apply -var="state_storage_account=<globally-unique-name>"
#
# Then init the main config against it (see docs/deploy-azure.md):
#   cd ..
#   terraform init -backend-config=envs/staging.backend.tfbackend

terraform {
  required_version = ">= 1.6.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
}

provider "azurerm" {
  subscription_id = var.subscription_id
  features {}
}

variable "subscription_id" {
  type = string
}

variable "location" {
  type    = string
  default = "eastus"
}

variable "state_resource_group" {
  description = "Resource group for Terraform state (separate from the app's RG so a `destroy` of the app never touches state)."
  type        = string
  default     = "rg-o2c-tfstate"
}

variable "state_storage_account" {
  description = "Globally-unique Storage Account name for Terraform state (3-24 lowercase alphanumeric chars)."
  type        = string
}

# This subscription's management group enforces a "Standard Tags" policy: every resource
# GROUP (not every resource) must carry these 4 tags or creation is denied. Discovered by
# probing `az group create` against the real policy — see docs/deploy-azure.md.
variable "std_owner" {
  type    = string
  default = "sridar.cs@global.ntt"
}

variable "std_environment" {
  type    = string
  default = "dev"
}

variable "std_project" {
  type    = string
  default = "order-to-cash-connector"
}

variable "std_billable" {
  type    = string
  default = "No"
}

resource "azurerm_resource_group" "state" {
  name     = var.state_resource_group
  location = var.location
  tags = {
    Project         = "order-to-cash-connector"
    ManagedBy       = "terraform-bootstrap"
    Std_Owner       = var.std_owner
    Std_Environment = var.std_environment
    Std_Project     = var.std_project
    Std_Billable    = var.std_billable
  }
}

resource "azurerm_storage_account" "state" {
  name                     = var.state_storage_account
  resource_group_name      = azurerm_resource_group.state.name
  location                 = azurerm_resource_group.state.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"

  blob_properties {
    versioning_enabled = true
  }
}

resource "azurerm_storage_container" "tfstate" {
  name                  = "tfstate"
  storage_account_id    = azurerm_storage_account.state.id
  container_access_type = "private"
}

output "state_resource_group" {
  value = azurerm_resource_group.state.name
}

output "state_storage_account" {
  value = azurerm_storage_account.state.name
}

output "state_container" {
  value = azurerm_storage_container.tfstate.name
}
