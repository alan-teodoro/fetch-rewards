# Redis Cloud GitHub Actions Automation

This repository provides a customer-ready Terraform and GitHub Actions reference for provisioning Redis Cloud Pro subscriptions, databases, and Redis Agent Memory services.

The workflows are manually triggered by the customer from GitHub Actions. They support:

- creating a Redis Cloud subscription and database together;
- creating or updating a database, including creating the subscription first when it does not exist;
- creating subscription-scoped infrastructure from a versioned JSON config file;
- creating Agent Memory services that can share an eligible database;
- destroying only a managed database;
- destroying a managed database and its managed subscription state;
- bootstrapping the S3 remote state bucket and GitHub Actions OIDC access in AWS.

## Repository Layout

```text
.github/workflows/rediscloud-database.yml   # Create/update database; creates subscription first when missing
.github/workflows/rediscloud-config.yml     # Create/update resources from a subscription config file
.github/workflows/rediscloud-destroy.yml    # Destroy a database; optionally destroy its subscription
.github/workflows/terraform-validate.yml    # Terraform fmt/init/validate checks
configs/fetch-rewards/subscriptions         # Subscription-scoped desired-state config files
docs/config-driven-architecture.md          # Config-driven architecture notes
docs/customer-setup.md                      # Customer onboarding runbook
docs/demo-guide.md                          # Customer demo checklist and talk track
modules/terraform_state_backend             # Reusable S3/OIDC backend module
scripts/check_s3_bucket.py                  # Backend bootstrap helper
scripts/rediscloud_config.py                # Config validator and Terraform tfvars renderer
stacks/state-backend                        # One-time AWS state backend bootstrap
stacks/subscription                         # Redis Cloud Pro subscription stack
stacks/database                             # Redis Cloud database and ACL stack
stacks/agent-memory                         # Redis Agent Memory service and data-plane API keys
```

Each stack keeps state isolated. The legacy workflows store subscription state under `subscriptions/<subscription>.tfstate` and database state under `databases/<subscription>/<database>.tfstate`. The config-driven workflow uses stable config keys, for example `subscriptions/dev-ai-us-east-1.tfstate`, `databases/dev-ai-us-east-1/shared_agent_memory.tfstate`, and `agent-memory/dev-ai-us-east-1/shopping_agent.tfstate`.

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

python3 scripts/rediscloud_config.py validate \
  --config configs/fetch-rewards/subscriptions/demo-ai-us-east-1.json
```

While Agent Memory support depends on the local provider build, validate
`stacks/agent-memory` with the Agent Memory provider branch. The validation
workflow builds that provider branch automatically by default.

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
- **Redis Cloud Config Apply** reads a subscription config file, renders Terraform variable files, and runs Terraform in subscription, database, then Agent Memory phases. In apply mode, each phase is fully planned before the saved plans for that phase are applied.
- **Redis Cloud Destroy** destroys a managed database and can optionally destroy the subscription when that database is the last one.

The database create workflow checks Redis Cloud first and shows the requested names, normalized Terraform names, and whether the subscription or database already exists. New subscription creation pauses on the `dev` GitHub environment when that environment has required reviewers configured. Subscription destroy requests use the same `dev` approval checkpoint. Terraform plan summaries are written before apply or destroy, then Terraform applies the saved plan. Re-running create with the same normalized subscription and database names updates the managed database to match the provided inputs. The legacy workflows expose only the most common inputs. Less common settings stay as Terraform defaults in `stacks/subscription/variables.tf` and `stacks/database/variables.tf`.

The config-driven workflow exposes `config_path`, `operation`, `credentials_profile`, the Agent Memory destroy override, and temporary provider-source inputs for the Agent Memory PoC. The default demo file is [configs/fetch-rewards/subscriptions/demo-ai-us-east-1.json](configs/fetch-rewards/subscriptions/demo-ai-us-east-1.json), which uses platform-managed Agent Memory models so it does not require model-provider secrets. See [docs/config-driven-architecture.md](docs/config-driven-architecture.md).

Use [docs/demo-guide.md](docs/demo-guide.md) for the customer demo checklist,
talk track, and PoC limitations.

For QA or other non-public Redis Cloud API environments, set `REDISCLOUD_URL`
or use the workflow's `qa` credentials profile with `REDISCLOUD_URL_QA`.

Agent Memory customer-managed LLM and embedding model credentials are referenced
by env var name in config files. The generic GitHub secret names used by the
examples are `AGENT_MEMORY_LLM_API_KEY` and
`AGENT_MEMORY_EMBEDDING_API_KEY`.

## Agent Memory Provider Status

The Agent Memory stack expects a Redis Cloud Terraform provider build that includes `rediscloud_agent_memory` and `rediscloud_agent_memory_api_key`. During the PoC, the config workflow can build that provider from the Agent Memory branch before running Terraform. Once Agent Memory support is available in the official provider, use `rediscloud_provider_source = registry` in the workflow and rely on the normal provider installation flow.
