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
  mock_resource "aws_s3_bucket" {
    defaults = { id = "customer-offline-state" }
  }
}

variables {
  bucket_name = "customer-offline-state"
}

run "initial_bootstrap" {
  command = apply
  assert {
    condition     = length(aws_s3_bucket.this) == 1
    error_message = "Bootstrap must own the bucket it creates."
  }
}

run "unchanged_bootstrap" {
  command = plan
  assert {
    condition     = length(aws_s3_bucket.this) == 1 && aws_s3_bucket.this[0].id == "customer-offline-state"
    error_message = "Repeating bootstrap must preserve the managed bucket identity."
  }
}
