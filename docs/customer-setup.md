# Customer Setup Guide

This guide describes how to install and operate the Redis Cloud automation repository in a customer-owned GitHub organization.

## 1. Copy the Repository

Create a new customer repository and copy this project into it. Keep the directory layout unchanged because the workflows reference the stack paths directly.

## 2. Create Redis Cloud API Keys

Create Redis Cloud programmatic API keys with permission to manage Pro subscriptions, databases, ACL rules, roles, and users.

Add these GitHub repository secrets:

```text
REDISCLOUD_ACCESS_KEY
REDISCLOUD_SECRET_KEY
```

## 3. Bootstrap AWS Remote State and OIDC

The Redis Cloud workflow uses an S3 bucket for Terraform state and a GitHub Actions OIDC IAM role to access that bucket.

Run the backend stack once from an administrator workstation that has AWS credentials and the AWS CLI installed:

```bash
cd stacks/state-backend
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`:

```hcl
aws_region  = "us-east-1"
bucket_name = "customer-rediscloud-terraform-state"

create_github_oidc_provider = true
create_github_actions_roles = true
github_actions_role_arns    = []
github_repository_owner     = "customer-github-org"
github_repository_name      = "redis-cloud-automation"
github_allowed_branches     = ["main"]

github_actions_role_names_by_environment = {
  prod = "GitHubActionsOIDCRedisCloudProd"
}
```

Then apply:

```bash
terraform init
terraform apply
```

If the AWS account already has the standard GitHub OIDC provider, set `create_github_oidc_provider = false` and either provide `github_oidc_provider_arn` or let the stack use the standard ARN path for the current account.

## 4. Configure GitHub Repository Settings

Add these GitHub repository secrets:

```text
TF_STATE_BUCKET
TF_STATE_REGION
```

Set `TF_STATE_BUCKET` to the `bucket_name` output and `TF_STATE_REGION` to the backend AWS region.

Add this GitHub repository or environment variable:

```text
AWS_GITHUB_ACTIONS_ROLE_ARN
```

Set it to the `managed_github_actions_role_arns.prod` output, or to an existing OIDC role ARN if the customer manages roles separately.

Create a GitHub environment named `prod`. Add required reviewers if the customer wants manual approval before apply or destroy jobs.

## 5. Validate the Repository

Run the validation workflow, or run locally:

```bash
terraform fmt -check -recursive

for stack in stacks/state-backend stacks/subscription stacks/database; do
  terraform -chdir="$stack" init -backend=false
  terraform -chdir="$stack" validate
done
```

## 6. Create or Update a Subscription and Database

Run **Actions > Redis Cloud Manage > Run workflow** with:

```text
operation = apply
github_environment = prod
subscription_mode = create-or-update-subscription
subscription_name = customer-prod
database_name = rewards-cache
```

Common database inputs:

- `database_dataset_size_in_gb`
- `database_throughput_ops_per_second`
- `database_redis_version`
- `database_persistence_mode`
- `database_data_eviction`
- `database_replication`
- `database_enable_tls`
- `database_enable_default_user`
- `database_source_ips_json`
- `database_alerts_json`
- `database_remote_backup_json`
- `database_acl_rule_string`

Example alert input:

```json
[
  { "name": "dataset-size", "value": 80 },
  { "name": "latency", "value": 10 }
]
```

Example backup input:

```json
{
  "interval": "every-24-hours",
  "time_utc": "03:00",
  "storage_type": "aws-s3",
  "storage_path": "s3://customer-redis-backups/rewards-cache"
}
```

## 7. Add or Update a Database in an Existing Subscription

Use this mode when Redis Cloud already has the subscription and Terraform should manage only the database and ACL resources:

```text
operation = apply
subscription_mode = existing-subscription
subscription_name = existing-subscription-name
database_name = new-database-name
```

The workflow skips the subscription stack and stores only database state under:

```text
databases/<subscription_name>/<database_name>.tfstate
```

## 8. Destroy Managed Resources

Destroy only the database and its ACL resources:

```text
operation = destroy
destroy_scope = database-only
subscription_mode = existing-subscription
```

Destroy a database and a subscription that were both managed by this repository:

```text
operation = destroy
destroy_scope = database-and-subscription
subscription_mode = create-or-update-subscription
```

The workflow destroys the database first, then the subscription.

## 9. Future Agent Memory Support

When Redis Cloud Agent Memory Terraform/API support is available:

1. Add a dedicated stack under `stacks/agent-memory`.
2. Store state under `agent-memory/<resource-name>.tfstate`.
3. Add the stack to `.github/workflows/terraform-validate.yml`.
4. Add a manual GitHub Actions workflow or extend `rediscloud-manage.yml` with a separate Agent Memory operation.
5. Keep Agent Memory inputs separate from database inputs so customers can provision, update, and destroy it independently.
