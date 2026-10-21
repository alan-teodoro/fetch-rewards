# Customer setup and operations

## Prerequisites

- A GitHub repository with this project and access to GitHub Actions.
- Terraform 1.11.1 or newer for local use. Actions pins its own version.
- An AWS account for private S3 state and GitHub OIDC. This backend account is independent of where Redis Cloud databases run.
- Redis Cloud administrative API credentials with access to subscriptions, databases, ACLs and Agent Memory.
- Account-specific billing information, networking CIDRs and source IP allowlists.

## Bootstrap state storage

Run once with AWS administrator credentials:

```bash
cd stacks/state-backend
cp terraform.tfvars.example terraform.tfvars
# Set your bucket, GitHub owner/repository, allowed branches and role options.
terraform init
terraform plan
terraform apply
```

Configure repository variables from the outputs:

| Variable | Purpose |
| --- | --- |
| `TF_STATE_BUCKET` | Private state and temporary reviewed-plan storage |
| `TF_STATE_REGION` | Region of that S3 bucket |
| `AWS_GITHUB_ACTIONS_ROLE_ARN` | OIDC role used by Actions to access the backend |
| `REDISCLOUD_RUNNER` | Optional runner label; defaults to ubuntu-latest |

Create a GitHub environment named `dev` with the reviewers required by your operating policy. Apply/destroy jobs use this environment; plan jobs do not. Review the OIDC role's allowed branch/environment conditions when copying the project to a new repository.

State includes generated database passwords and data-plane API keys. Keep the bucket private, encrypted and versioned, restrict IAM access and configure retention for old versions of temporary plan bundles. Never publish state, plans or generated tfvars as public artifacts.

## Credentials and provider

Configure repository secrets `REDISCLOUD_ACCESS_KEY` and `REDISCLOUD_SECRET_KEY`. Leave `REDISCLOUD_URL` unset for the public Redis Cloud API; only set it when intentionally using another endpoint. A private provider checkout can require `REDISCLOUD_PROVIDER_CHECKOUT_TOKEN`.

Agent Memory is not yet available in the official provider release used by this project. The manual workflows default to `rediscloud_provider_source = branch` and an exact tested provider commit. Use the same commit for plan, apply and destroy. The apply job reuses the reviewed binary. Once an official version includes Agent Memory, update the lock files, test the upgrade and switch to `registry`.

## Prepare the JSON

The complete example is `configs/fetch-rewards/subscriptions/demo-ai-us-east-1.json`. Another customer can copy it to `configs/<customer>/subscriptions/<name>.json`.

Set the customer/environment metadata, a unique `subscription_key`, subscription/database/store names, region, deployment CIDR and source IPs. Review every account-specific value. The sample IPs and billing selector belong to the demonstration account.

For credit-card billing, set `subscription.payment_method_id` or both `payment_card_type` and `payment_card_last_four`. The reusable stack has no default customer card. Marketplace billing uses its separate `payment_method` option.

Each database and store is a map entry. A store's `database` refers to a database map key, not its display name. Keep `subscription_key`, database keys and store keys stable. Changing a display name is a resource update when supported; changing a state key requires migration.

`mode = managed` creates and owns a resource. `mode = external` references a resource owned elsewhere. External subscriptions can provide `subscription_id`; external databases can provide `database_id`. Ownership changes for previously managed entries require explicit reconciliation rather than silently abandoning state.

The example starts with one store and platform-managed models, so no external model-provider key is needed. See [the walkthrough](demo-guide.md) to add another store.

## Run the pipeline

Open Actions → **Redis Cloud Config Apply** and select the branch containing the desired JSON.

| Input | Meaning |
| --- | --- |
| `config_path` | `configs/<customer>/subscriptions/<file>.json` |
| `operation` | `plan` for preview or `apply` for reviewed deployment |
| `rediscloud_provider_source` | `branch` until the feature is released; then `registry` |
| `rediscloud_provider_ref` | Exact tested provider commit in branch mode |

Read the plan job summary. It lists creates, updates, deletions, replacements and changed field names. Credential and generated-key values are omitted. A store replacement generates a new store ID and new keys. Context is not automatically migrated; update application references and plan any migration before applying.

For `apply`, one environment approval covers the complete configuration. Subscription and database creation or renaming can defer downstream plans; those steps are identified before approval and planned after their dependencies exist. The provider binary and inputs remain frozen. Approval must begin within one hour of planning. An unchanged run requests no approval.

Execution follows subscription → databases → stores. A failure stops subsequent work and does not roll back completed resources. Fix the configuration or dependency and run again, reviewing the new plan.

## Delete resources

Remove a managed store from `agent_memory_stores`, commit and run Config Apply. Its existing state produces a deletion plan. Other stores, its database and its subscription remain managed.

Remove a database from `databases` to propose deleting the database and its ACLs. Remove dependent stores too; references to absent database keys fail validation. The pipeline destroys omitted stores before omitted databases. Other users of the database can still prevent deletion in the API.

For a full teardown, use **Redis Cloud Config Destroy**, select the same JSON and set `confirm_destroy = true`. Use `agent_memory_key` to target just one store. The workflow includes previously managed resources omitted from the file when doing a full teardown. External resources and the backend remain intact.

Deleting a file does not run Terraform. Never delete the last configuration before tearing down its infrastructure. If a selective destroy leaves its entry in the JSON, the next apply will recreate it.

## Keys and model credentials

Generated data-plane API keys are available as sensitive outputs in each store's Terraform state. `secret_ref` records a desired destination only; this repository does not automatically publish values to Secrets Manager. Plan a secret-delivery step appropriate to your applications before handoff.

Customer-managed models require both `llm` and `embedding`. Their `credentials.api_key_env_var` names reference environment variables exposed to the renderer. Actions currently exposes the GitHub secrets `AGENT_MEMORY_LLM_API_KEY` and `AGENT_MEMORY_EMBEDDING_API_KEY`.

Set `credentials.api_key_version` to a positive integer (default 1). When rotating a model key, change the GitHub secret and increase this version in JSON. The provider's `api_key` does not save model keys in resource state. Renderer tfvars and reviewed plan bundles remain sensitive and must stay private and encrypted; the root inputs are not ephemeral.

## Verify and maintain

Run **Terraform Validate** for format, configuration, regression tests and stack validation. Use [architecture notes](config-driven-architecture.md) when modifying the rendering/execution code. The `scripts/internal/`, provider validation workflow and historical test fixtures support provider development; customer operations only need the config workflows.

Before using a new provider version or changing the stack contracts, rehearse create, no-op reapply, update, addition, selective deletion and full teardown on an isolated subscription. Rehearse store replacement separately with known test memories and sessions; check both application visibility and physical database retention rather than assuming either behavior.
