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

Create a GitHub environment named `dev` and configure required reviewers for it. The **Redis Cloud Create** workflow uses this environment only when the requested subscription does not already exist. The **Redis Cloud Destroy** workflow uses the same environment only when `destroy_subscription` is true. Database-only updates and destroys continue without this checkpoint.

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

## 6. Provision or Update a Database

Run **Actions > Redis Cloud Create > Run workflow**.

Use this workflow for both common provisioning paths:

- If the normalized subscription name already exists in Redis Cloud, Terraform creates or updates only the database and ACL resources.
- If the normalized subscription name does not exist, the workflow waits for approval on the `dev` environment, then creates the subscription and database.

Common inputs:

- `subscription_name`
- `database_name`
- `subscription_region`
- `subscription_multi_az`
- `dataset_size_in_gb`
- `high_availability`
- `throughput_ops_per_second`
- `redis_version`
- `persistence_mode`
- `data_eviction`

The workflow accepts user-friendly names and normalizes them internally for Terraform state and Redis Cloud resources. For example, `Fetch Rewards Prod` becomes `fetch-rewards-prod`. The GitHub Actions summary shows both requested and normalized names.

`subscription_region` is limited to the supported US AWS regions exposed by the workflow: `us-east-1`, `us-east-2`, `us-west-1`, and `us-west-2`. `subscription_multi_az` defaults to `true`. These subscription inputs are used only when the workflow creates a new subscription.

The database inputs are treated as desired state. To update an existing managed database, run the same workflow again with the same normalized `subscription_name` and `database_name`, and provide the desired final values for every exposed setting.

The Redis version dropdown matches the console options currently exposed by the workflow: `6.2`, `7.2`, `7.4`, `8.2`, `8.4`, and `8.6`. Data persistence options are `none`, `aof-every-1-second`, `aof-every-write`, `snapshot-every-1-hour`, `snapshot-every-6-hours`, and `snapshot-every-12-hours`. Data eviction options are `allkeys-lru`, `allkeys-lfu`, `allkeys-random`, `volatile-lru`, `volatile-lfu`, `volatile-random`, `volatile-ttl`, and `noeviction`.

Redis Flex is disabled, Redis-provided cloud accounts and new VPC deployment are used, maintenance windows stay automatic, and resource tags are not exposed in the workflow.

The workflow stores state under:

```text
subscriptions/<normalized_subscription_name>.tfstate
databases/<normalized_subscription_name>/<normalized_database_name>.tfstate
```

Before running Terraform, the workflow queries the Redis Cloud API:

- If the subscription does not exist, the workflow creates it.
- If the database already exists, Terraform imports it into the selected state when needed, then applies the requested settings.
- If the database does not exist, Terraform creates it.

## 7. Destroy Managed Resources

Run **Actions > Redis Cloud Destroy > Run workflow**.

Destroy only a database and its ACL resources:

```text
subscription_name = fetch-rewards-prod
database_name = session-cache
destroy_subscription = false
confirm_destroy = true
```

Destroy a database and its managed subscription when that database is the last one:

```text
subscription_name = fetch-rewards-prod
database_name = session-cache
destroy_subscription = true
confirm_destroy = true
```

The workflow checks Redis Cloud before running Terraform. If `destroy_subscription` is true, it blocks when the subscription has more than one database or when the requested database is not the last database in that subscription. The subscription destroy path waits for approval on the `dev` environment.

Database state is stored under `databases/<normalized_subscription_name>/<normalized_database_name>.tfstate`. Subscription state is stored under `subscriptions/<normalized_subscription_name>.tfstate`. Only use `destroy_subscription = true` for subscriptions managed by this repository.

## 8. Future Agent Memory Support

When Redis Cloud Agent Memory Terraform/API support is available:

1. Add a dedicated stack under `stacks/agent-memory`.
2. Store state under `agent-memory/<resource-name>.tfstate`.
3. Add the stack to `.github/workflows/terraform-validate.yml`.
4. Add a manual GitHub Actions workflow for Agent Memory operations.
5. Keep Agent Memory inputs separate from database inputs so customers can provision, update, and destroy it independently.
