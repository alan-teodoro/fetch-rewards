mock_provider "aws" {
  mock_data "aws_partition" {
    defaults = { partition = "aws" }
  }
  mock_data "aws_caller_identity" {
    defaults = { account_id = "111122223333" }
  }
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  mock_data "aws_s3_bucket" {
    defaults = { id = "customer-offline-state" }
  }
}

variables {
  bucket_name   = "customer-offline-state"
  create_bucket = false
}

run "reference_existing_bucket" {
  command = apply
  assert {
    condition     = length(aws_s3_bucket.this) == 0 && aws_s3_bucket_versioning.this.bucket == "customer-offline-state"
    error_message = "An external bucket must not be created or adopted, but its security settings are configured."
  }
}

run "unchanged_external_bootstrap" {
  command = plan
  assert {
    condition     = length(aws_s3_bucket.this) == 0 && aws_s3_bucket_server_side_encryption_configuration.this.bucket == "customer-offline-state"
    error_message = "Repeating external bucket bootstrap must preserve its ownership."
  }
}
