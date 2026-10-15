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

For non-public Redis Cloud API environments, also set `REDISCLOUD_URL` as a
repository variable or secret. Leave it unset for the public Redis Cloud API.

If Agent Memory uses customer-managed LLM and embedding providers, add the
model provider secrets referenced by the config files. The default examples use:

```text
AGENT_MEMORY_LLM_API_KEY
AGENT_MEMORY_EMBEDDING_API_KEY
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

Create a GitHub environment named `dev` and configure required reviewers for
it. The **Redis Cloud Config Apply** workflow uses this environment when
`operation = apply`; `operation = plan` runs without approval. The **Redis Cloud
Config Destroy** workflow always uses this environment before destroying
resources. Apply blocks replacement/deletion of Agent Memory entries still
present in the JSON. Removing managed Agent Memory or database entries produces
deletion plans for review before the same approval.

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

For the config-driven Agent Memory PoC, the workflows can build the Redis Cloud
provider from the Agent Memory branch before running Terraform. The provider
repository is fixed in the workflow; the default workflow inputs use:

```text
rediscloud_provider_source     = branch
rediscloud_provider_ref        = 39d6752e915a71c7b58f7ee4b0f63304be3528df
```

If that provider branch is private, add a repository secret named
`REDISCLOUD_PROVIDER_CHECKOUT_TOKEN` with read access to the provider
repository.

For validation runs, these optional repository variables can override the same
provider source/ref defaults:

```text
REDISCLOUD_PROVIDER_SOURCE
REDISCLOUD_PROVIDER_REF
```

Set `REDISCLOUD_PROVIDER_SOURCE = registry` once the official Redis Cloud
provider release includes `rediscloud_agent_memory` and
`rediscloud_agent_memory_api_key`.

## 5. Validate the Repository

Run the validation workflow, or run locally:

```bash
terraform fmt -check -recursive

for stack in stacks/state-backend stacks/subscription stacks/database; do
  terraform -chdir="$stack" init -backend=false
  terraform -chdir="$stack" validate
done

python3 scripts/rediscloud_config.py validate \
  --config configs/fetch-rewards/subscriptions/demo-ai-us-east-1.json
```

While Agent Memory support depends on the provider branch, the validation
workflow builds that branch and validates `stacks/agent-memory` automatically.

## 6. Provision or Update Resources

Run **Actions > Redis Cloud Config Apply > Run workflow**.

Use the [Demo Guide](demo-guide.md) as the demo checklist and talk track.

Common inputs:

- `config_path`: path to one subscription config file, for example `configs/fetch-rewards/subscriptions/demo-ai-us-east-1.json`.
- `operation`: `plan` or `apply`.
- `rediscloud_provider_source`: keep `branch` while Agent Memory support is unreleased; switch to `registry` after the official provider includes the Agent Memory resources.
- `rediscloud_provider_ref`: provider branch, tag, or commit used only when `rediscloud_provider_source` is `branch`.

The config-driven workflow renders Terraform tfvars from the JSON file and runs stacks in dependency phases:

1. `stacks/subscription`
2. `stacks/database`
3. `stacks/agent-memory`

In `apply` mode, the customer reviews one summary and approves the `dev`
environment **once for the whole execution**, including subscription, databases,
and every configured Agent Memory. Open the run summary or the non-sensitive
`plan-summary-rollout-<attempt>` artifact before approving. With existing
dependencies, actual plans for all stacks are generated before approval and
those saved files are applied afterward. An unchanged execution needs no approval.

On fresh creation, replacement or renaming of a dependency, the summary shows
its actual plan plus an inventory of dependent resources whose plans are
**deferred**. Review the linked configuration at the exact commit: approval
also authorizes planning and applying those dependent stacks after the parent
exists. A deferred inventory is not a Terraform plan. The job plans all stacks
in each deferred phase and checks Agent Memory deletion/replacement guards
before applying any sibling. A failure stops later phases; completed changes
remain in Terraform state and are not automatically rolled back. Correct the
cause and run a new review/apply to converge.

Plan-only mode never applies and skips downstream plans with unavailable
dependencies. The approved apply job downloads the exact provider binary,
reviewed plans and frozen deferred variable files from encrypted private S3,
verifying SHA-256 and commit/run/attempt metadata. It reuses available reviewed
plans; it generates only explicitly deferred plans afterward and includes them
in the execution summary. Approval must start within one hour of planning;
start a new run or rerun all jobs if expired or if state became stale. Do not
rerun only a failed apply from another run attempt. Raw plans and provider
binaries are never published as GitHub artifacts. Current S3 bundles are deleted
after apply; bucket versioning retains historical versions under backend retention.

The destroy workflow reviews every selected deletion plan first, then requests
one approval and applies those saved plans in reverse dependency order.
Rehearse configuration updates and an unchanged reapply before relying on the
flow for a customer demonstration. See the maintenance example in the demo
guide.

The workflow supports managed and external resources in the same file. Use `external` for existing subscriptions or databases that Terraform should reference but not create.

For external subscriptions, the config can include both `name` and
`subscription_id`. Use `subscription_id` when database creation should target an
existing subscription by ID instead of relying on Redis Cloud subscription
lookup by name.

Agent Memory API key values are not printed in workflow summaries. They are Terraform-sensitive and stored in the Agent Memory state. Use `secret_ref` in the config file to record where the generated data-plane key should be published by the runner or a follow-up secret publishing step.

Customer-managed LLM and embedding API keys are also not stored in JSON. The
config references environment variable names with `api_key_env_var`; the
workflow exposes the corresponding GitHub secrets to the renderer.

The official Redis Cloud provider currently does not include the Agent Memory
resources used by this PoC. Until it does, keep
`rediscloud_provider_source = branch` when running the config workflow.

## Removing entries through Config Apply

Remove an Agent Memory entry from `agent_memory_stores`, commit and run Config
Apply. The review lists its store, keys and validation resources as deletions.
After approval, its saved deletion plan runs before any creates/updates. Other
agents and the backing database remain managed.

Removing a database entry from `databases` similarly proposes deletion of the
database and its ACLs. Remove its dependent agents too; references to a missing
database key fail configuration validation. References to the removed database
by ID also block reconciliation. Omitted agents are removed before databases.
Other dependencies outside this configuration may still cause the API to reject
a database deletion; a failure stops subsequent work without automatic rollback.

Discovery reads only current `.tfstate` objects directly under
`subscriptions/<subscription_key>/agent-memory/` and `databases/` in the configured
backend. Empty states from previous deletions are ignored. Historical versions,
lock files, review bundles and other subscription namespaces are excluded. Only
states with recognized stack resources are eligible; unknown or partially
created states without a primary resource require manual reconciliation.
Failure to list or read states stops the review rather than assuming no deletions.

Keep `subscription_key` and resource map keys stable and unique. Changing a key
is a state migration; a same-named resource appearing under another key is
rejected. Changing a state-managed entry to `external` requires an explicit
ownership transfer, not automatic deletion or a silent orphan. Existing external
entries without managed state are preserved. Deleting the entire JSON file does
not run a workflow or delete anything. Removing the subscription itself still
requires Config Destroy.

`operation = plan` displays omitted-resource deletion plans without applying or
requesting approval. `operation = apply` requires the existing single approval,
uses the saved plans and exact reviewed provider, and stops on failure. State
changes after planning cause Terraform to reject stale saved plans; generate a
new review instead of retrying an old apply.

## 7. Destroy Managed Resources

Run **Actions > Redis Cloud Config Destroy > Run workflow**.

Common inputs:

- `config_path`: the same subscription config file used for apply.
- `confirm_destroy`: must be `true`.
- `agent_memory_key`: optional stable config key, such as `support_agent`, to
  destroy only that Agent Memory service and its keys. Leave empty to destroy
  all managed resources in the config.
- `rediscloud_provider_source`: keep `branch` while Agent Memory support is unreleased; switch to `registry` after the official provider includes the Agent Memory resources.
- `rediscloud_provider_ref`: provider branch, tag, or commit used only when `rediscloud_provider_source` is `branch`.

The destroy workflow renders the config file and destroys only managed resources
described by that file, plus omitted Agent Memory/database states in the same
subscription namespace when performing full cleanup. It runs in reverse dependency order:

1. Agent Memory services and their data-plane API keys.
2. Managed databases and their ACL resources.
3. The managed subscription, only when the config marks the subscription as
   `managed`.

External resources in the config are not destroyed. Before each destroy, the
workflow writes a Terraform destroy plan summary to the GitHub Actions summary
and then applies the saved destroy plan file. Use this workflow to remove the
whole subscription or selectively destroy a still-configured agent. Normal
Config Apply also reviews deletion of Agent Memory/database entries removed
from the JSON.

For selective Agent Memory deletion, keep the service in the JSON until the
destroy run succeeds, then remove its entry and commit the updated config. An
apply while the deleted entry is still present recreates the service. Other
Agent Memory services, the database, and the subscription are preserved when
`agent_memory_key` is supplied. Unknown keys and external services are rejected
before the approval checkpoint.
