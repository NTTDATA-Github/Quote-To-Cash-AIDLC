# Remote state: S3 bucket + DynamoDB lock table (created once by infra/terraform/bootstrap).
# Values are supplied at init time so the same config serves any environment:
#   terraform init -backend-config=envs/staging.s3.tfbackend
# See docs/deploy-aws.md. Local (floci) runs use a local backend — pass -backend=false
# or init without this partial config in that flow (the bootstrap doc explains both).
terraform {
  backend "s3" {
    # key / bucket / region / dynamodb_table come from the -backend-config file.
    encrypt = true
  }
}
