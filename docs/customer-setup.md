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

The backend stack grants S3 state access through a customer-managed IAM policy attached to the GitHub Actions role. Avoid adding this access as an inline role policy when reusing a shared OIDC role across repositories, because AWS applies a small total-size limit to inline policies on a role.

## 4. Configure GitHub Repository Settings

Add these GitHub repository variables:

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

The workflows assume a single GitHub Actions OIDC role, stored in `AWS_GITHUB_ACTIONS_ROLE_ARN`. GitHub environments are not required for OIDC.

The subscription stack defaults to Redis Cloud credit-card billing and looks up the saved payment method by card type and last four digits, matching the current PS test account baseline. For a customer account, update the defaults in `stacks/subscription/variables.tf` or override them with repository variables.

For the GitHub workflow path, use optional repository variables instead:

```text
REDISCLOUD_PAYMENT_METHOD
REDISCLOUD_PAYMENT_METHOD_ID
REDISCLOUD_PAYMENT_CARD_TYPE
REDISCLOUD_PAYMENT_CARD_LAST_FOUR
```

For credit-card billing, either set `REDISCLOUD_PAYMENT_METHOD_ID` to the Redis Cloud payment method ID, or set `REDISCLOUD_PAYMENT_CARD_TYPE` and `REDISCLOUD_PAYMENT_CARD_LAST_FOUR` so Terraform can look it up. Leave these unset only for direct contract or invoiced accounts when Redis Cloud does not require payment information.

Redis Cloud resource tags are not exposed in the manual workflows. They remain disabled by default because internal Redis Cloud cloud accounts do not allow them. Enable `enable_resource_tags` only through Terraform defaults for customer accounts where Redis Cloud supports resource tagging.

## 5. Validate the Repository

Run the validation workflow, or run locally:

```bash
terraform fmt -check -recursive

for stack in stacks/state-backend stacks/subscription stacks/database; do
  terraform -chdir="$stack" init -backend=false
  terraform -chdir="$stack" validate
done
```

## 6. Create a Subscription and Initial Database

Run **Actions > Redis Cloud Create > Run workflow**.

Use this workflow when Terraform should manage both the subscription state and the initial database state.

Common inputs:

- `subscription_name`
- `database_name`
- `subscription_region`
- `database_dataset_size_in_gb`
- `database_high_availability`
- `database_throughput_ops_per_second`
- `database_redis_version` (optional; leave blank for the Redis Cloud default)
- `persistence_mode`

Use lowercase, hyphen-separated names for `subscription_name` and `database_name`, for example `fetch-rewards-prod` and `session-cache`.

Subscription sizing uses the initial database size, high availability, and throughput inputs. Multi-AZ is enabled by default, Redis Flex is disabled, Redis-provided cloud accounts and new VPC deployment are used, maintenance windows stay automatic, and resource tags are not exposed in the workflow.

The workflow stores state in both paths:

```text
subscriptions/<subscription_name>.tfstate
databases/<subscription_name>/<database_name>.tfstate
```

## 7. Add or Update a Database in an Existing Subscription

Run **Actions > Redis Cloud Database > Run workflow**.

Use this workflow when Redis Cloud already has the subscription and Terraform should manage only the database and ACL resources.

Common inputs:

- `subscription_name`
- `database_name`
- `dataset_size_in_gb`
- `high_availability`
- `throughput_ops_per_second`
- `redis_version` (optional; leave blank for the Redis Cloud default)
- `persistence_mode`

Use lowercase, hyphen-separated names for `subscription_name` and `database_name`, for example `fetch-rewards-prod` and `session-cache`.

This workflow is an apply operation. To update an existing managed database, run the same workflow again with the same `subscription_name` and `database_name`, and provide the desired final values for every exposed setting. Treat the inputs as desired state, not as a partial patch.

Leave `redis_version` blank to let Redis Cloud choose its current default for new databases. Set an explicit value such as `8.6` when you need to request a specific version or upgrade an existing managed database.

The workflow stores only database state under:

```text
databases/<subscription_name>/<database_name>.tfstate
```

Before running Terraform, the workflow queries the Redis Cloud API:

- If the subscription name is wrong or does not exist, the workflow fails before Terraform runs.
- If the database already exists, the summary shows that it is an update path.
- If the database does not exist, Terraform creates it.

## 8. Destroy a Managed Database

Run **Actions > Redis Cloud Database Destroy > Run workflow**.

Destroy the database and its ACL resources:

```text
subscription_name = fetch-rewards-prod
database_name = session-cache
confirm_destroy = true
```

This workflow only requires the database name because database state is stored under:

```text
databases/<subscription_name>/<database_name>.tfstate
```

## 9. Destroy a Managed Subscription

Run **Actions > Redis Cloud Subscription Destroy > Run workflow**.

```text
subscription_name = fetch-rewards-prod
confirm_destroy = true
```

This workflow does not require a database name. It checks Redis Cloud before running Terraform and fails if the subscription still has databases. Destroy managed databases first, then destroy the subscription. Only use this workflow for subscriptions created through **Redis Cloud Create** and managed by this repository.

## 10. Future Agent Memory Support

When Redis Cloud Agent Memory Terraform/API support is available:

1. Add a dedicated stack under `stacks/agent-memory`.
2. Store state under `agent-memory/<resource-name>.tfstate`.
3. Add the stack to `.github/workflows/terraform-validate.yml`.
4. Add a manual GitHub Actions workflow for Agent Memory operations.
5. Keep Agent Memory inputs separate from database inputs so customers can provision, update, and destroy it independently.
