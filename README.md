# Redis Cloud GitHub Actions Automation

This repository provides a customer-ready Terraform and GitHub Actions reference for provisioning Redis Cloud Pro subscriptions and databases.

The workflows are manually triggered by the customer from GitHub Actions. They support:

- creating a Redis Cloud subscription and database together;
- creating or updating a database, including creating the subscription first when it does not exist;
- destroying only a managed database;
- destroying a managed database and its managed subscription state;
- bootstrapping the S3 remote state bucket and GitHub Actions OIDC access in AWS.

## Repository Layout

```text
.github/workflows/rediscloud-database.yml   # Create/update database; creates subscription first when missing
.github/workflows/rediscloud-destroy.yml    # Destroy a database; optionally destroy its subscription
.github/workflows/terraform-validate.yml    # Terraform fmt/init/validate checks
docs/customer-setup.md                      # Customer onboarding runbook
modules/terraform_state_backend             # Reusable S3/OIDC backend module
scripts/check_s3_bucket.py                  # Backend bootstrap helper
stacks/state-backend                        # One-time AWS state backend bootstrap
stacks/subscription                         # Redis Cloud Pro subscription stack
stacks/database                             # Redis Cloud database and ACL stack
```

Each stack keeps state isolated. Subscription state is stored under `subscriptions/<subscription>.tfstate`; database state is stored under `databases/<subscription>/<database>.tfstate`. The backend also reserves `agent-memory/*` for future Agent Memory resources.

## Prerequisites

- Terraform `>= 1.10`
- AWS CLI configured for the backend bootstrap account
- Redis Cloud API keys with permission to manage Pro subscriptions, databases, ACL rules, roles, and users
- An AWS account for the Terraform S3 backend
- GitHub repository secrets and variables described in [docs/customer-setup.md](docs/customer-setup.md)

## Local Validation

Run the same checks used by CI:

```bash
terraform fmt -check -recursive

for stack in stacks/state-backend stacks/subscription stacks/database; do
  terraform -chdir="$stack" init -backend=false
  terraform -chdir="$stack" validate
done
```

## Backend Bootstrap

Before the GitHub Actions workflow can manage Redis Cloud resources, bootstrap the AWS backend:

```bash
cd stacks/state-backend
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars for the customer AWS account and GitHub repository.
terraform init
terraform apply
```

Use the outputs to configure the customer repository:

- variable `TF_STATE_BUCKET`
- variable `TF_STATE_REGION`
- variable `AWS_GITHUB_ACTIONS_ROLE_ARN`

## Manual Workflows

Use one of the focused manual workflows:

- **Redis Cloud Create** creates or updates a database. If the subscription name is not found in Redis Cloud, the workflow creates the subscription first and then creates the database.
- **Redis Cloud Destroy** destroys a managed database and can optionally destroy the subscription when that database is the last one.

The database create workflow checks Redis Cloud first and shows the requested names, normalized Terraform names, and whether the subscription or database already exists. New subscription creation pauses on the `dev` GitHub environment when that environment has required reviewers configured. Subscription destroy requests use the same `dev` approval checkpoint. Terraform plan summaries are written before apply or destroy, then Terraform applies the saved plan. Re-running create with the same normalized subscription and database names updates the managed database to match the provided inputs. The workflows expose only the most common inputs. Less common settings stay as Terraform defaults in `stacks/subscription/variables.tf` and `stacks/database/variables.tf`. Generated tfvars are written at runtime and never committed. Sensitive values such as the generated ACL password remain Terraform-sensitive and are not written to the GitHub summary.

## Future Agent Memory Resources

When Redis Cloud Agent Memory Terraform/API support is available, add a new stack under `stacks/agent-memory` and store its state under `agent-memory/<name>.tfstate`. Keep Agent Memory state separate from subscription and database state so customers can add, update, or remove those resources independently.
