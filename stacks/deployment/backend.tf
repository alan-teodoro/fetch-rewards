# The backend key is selected from subscription_key by the CLI/workflow.
# Only Terraform reads and writes state; scripts do not inspect its contents.
terraform {
  backend "s3" {
    use_lockfile = true
  }
}
