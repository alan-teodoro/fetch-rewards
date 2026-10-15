# Config-Driven Redis Cloud Architecture

This repository is moving toward subscription-scoped configuration files. A
config file describes the desired Redis Cloud resources for one subscription:
the subscription itself, its databases, and the Agent Memory services that use
those databases.

## File Layout

```text
configs/fetch-rewards/subscriptions/
  demo-ai-us-east-1.json
  dev-ai-us-east-1.json
```

Use one file per subscription. The `environment` field can be `dev`, `prod`, or
any customer-specific environment label. This allows multiple dev or prod
subscriptions without changing the runner. Production files should follow the
same pattern once the customer confirms names, regions, billing, and networking.

The checked-in `demo-ai-us-east-1.json` file is intentionally verbose, but it
starts with one Agent Memory and uses platform-managed models so it can run without model-provider
secrets. Customers can use it as the demo input and then remove unused fields as
their production config stabilizes. Customer-managed LLM and embedding configs
use the same shape, but reference model-provider credentials by environment
variable name rather than storing secrets in JSON.

## Resource Modes

Each resource supports a `mode`:

- `managed`: Terraform should create and update the resource.
- `external`: the resource already exists; Terraform can reference it, but this
  config does not manage its lifecycle.

This supports the common Agent Memory paths:

- create subscription, database, and Agent Memory together;
- use an existing subscription and create database plus Agent Memory;
- use existing subscription and database and create only Agent Memory.

For existing subscriptions, keep the human-readable `name` in the file and set
`subscription_id` when the Redis Cloud API key cannot resolve subscriptions by
name or when the customer prefers ID-based references. Managed subscriptions do
not use `subscription_id`; Terraform discovers the ID after creating them.

Existing resources should start as `external`. If the customer wants Terraform
to adopt an existing subscription, database, or Agent Memory service as
`managed`, import the resource into the matching state first. The config runner
does not automatically import existing infrastructure.

Removing a managed Agent Memory or database entry generates a deletion plan
from its current state in the same `subscription_key` namespace. Config Apply
reviews those saved plans before approval, removes agents/keys before databases/ACLs,
then applies creates/updates. External entries are preserved; ownership changes
require explicit state migration. Subscription removal remains an explicit Config
Destroy operation. Deleting the whole JSON file does not trigger reconciliation.
See [the customer guide](customer-setup.md#removing-entries-through-config-apply)
for dependency checks, state discovery and recovery behavior.

## Stable Keys

Map keys such as `shared_agent_memory` and `shopping_agent` are stable internal
identities. They are used for state paths and references. Resource names can
change over time, but changing a stable key should be treated as a migration.

Example state layout:

```text
subscriptions/dev-ai-us-east-1/subscription.tfstate
subscriptions/dev-ai-us-east-1/databases/shared_agent_memory.tfstate
subscriptions/dev-ai-us-east-1/agent-memory/shopping_agent.tfstate
```

## Agent Memory Compatibility

Redis Agent Memory currently requires an eligible Redis Cloud database. During
public preview, Agent Memory requires the database `default` user to be enabled.
For managed databases used by Agent Memory, set:

```json
{
  "agent_memory_compatible": true
}
```

The config renderer then writes `enable_default_user = true` to the generated
database tfvars unless the config already sets it. If the config explicitly sets
`enable_default_user` to `false`, validation fails.

## Secrets

Do not put secret values in config files. Use `secret_ref` for references to the
customer's secret backend.

Agent Memory has a data-plane API key that is different from the Redis Cloud
account API key. When Terraform creates `rediscloud_agent_memory_api_key`, the
secret value is returned only on creation and is stored in Terraform state as a
sensitive value. The generated key should be copied into the referenced secret
backend by the runner or by a follow-up secret publishing step.

Example:

```json
{
  "api_keys": {
    "runtime": {
      "mode": "managed",
      "name": "shopping-agent-runtime",
      "secret_ref": "aws-secrets-manager:/fetch-rewards/prod/shopping/runtime"
    }
  }
}
```

Customer-managed Agent Memory model credentials are input secrets. Reference
them with environment variables in the config file; the renderer copies the
secret value into generated Terraform tfvars outside git:

```json
{
  "llm": {
    "provider": "openai",
    "model": "gpt-4o-mini",
    "credentials": {
      "type": "apiKey",
      "api_key_env_var": "AGENT_MEMORY_LLM_API_KEY"
    }
  },
  "embedding": {
    "provider": "openai",
    "model": "text-embedding-3-small",
    "credentials": {
      "type": "apiKey",
      "api_key_env_var": "AGENT_MEMORY_EMBEDDING_API_KEY"
    }
  }
}
```

The Agent Memory API requires `llm` and `embedding` to be configured together.
When `embedding` is configured, `long_term_ttl_seconds` must also be set.
Customer-managed models must be configured when the store is first created; the
API does not allow moving an existing platform-managed store to
customer-managed models later. The embedding provider/model is treated as
immutable after creation, so changing it should be planned as a migration.

## Local Usage

Validate a config file:

```bash
python3 scripts/rediscloud_config.py validate \
  --config configs/fetch-rewards/subscriptions/dev-ai-us-east-1.json
```

Render Terraform variable files and a manifest:

```bash
python3 scripts/rediscloud_config.py render \
  --config configs/fetch-rewards/subscriptions/dev-ai-us-east-1.json \
  --out-dir .generated/rediscloud/dev-ai-us-east-1
```

The manifest tells any runner which stack tfvars to apply and which remote state
key to use. GitHub Actions should be a thin wrapper around the same commands.
The workflow applies by dependency phase: subscription, databases, then Agent
Memory. In `apply` mode, `rediscloud-phase.yml` uses a single `rollout`
review bundle and one `dev` environment gate for the entire configuration.
Existing dependency chains are fully planned before approval. Missing or
renamed parents defer downstream plans; the review explicitly identifies those
resources and links to the approved configuration revision. Deferred variable
files are frozen inside the encrypted bundle. After approval, the controller
applies reviewed plans and produces only the deferred plans as dependencies
become available. It checks all Agent Memory plans before applying any service
in that phase. A failure stops later work without automatic rollback.

The exact provider binary, saved plans, frozen inputs and lockfiles are bound
to checksums and commit/run/attempt metadata. Approval must start within one
hour. Destroy reviews all selected states before a single gate and applies in
reverse order. Raw plans stay out of GitHub artifacts; bucket versioning retains
previous S3 bundle versions according to backend retention policy. In `plan` mode, the runner inspects each dependency
plan. A managed subscription or database that already exists can be used for
downstream plans, including when its settings are updated in place. Downstream
stacks are skipped when their subscription or database is being created,
replaced, or renamed, because the target name is not available until apply.

The apply and destroy workflows share one concurrency group so operations from
different config paths cannot modify shared infrastructure at the same time.

For selective cleanup, the destroy workflow accepts `agent_memory_key`, such
as `support_agent`. It validates that the key exists and is managed before
approval, then renders only that Agent Memory stack as a destroy target.
Subscription and database dependencies are referenced as external for this
run, preserving their existing state keys and lifecycle in the original config.
The original JSON is not rewritten. Remove the deleted entry from the desired
config after destroy succeeds, or a later apply will create it again. An empty
selector retains the complete managed-resource cleanup behavior.

## Agent Memory Provider During the PoC

Until Agent Memory support is available in the official Redis Cloud Terraform
provider release, the GitHub Actions workflow can build the provider directly
from the Agent Memory provider branch. This lets the demo use the production
Redis Cloud API with a provider that has not been published to the Terraform
Registry yet.

The config workflows expose these provider inputs while Agent Memory support is
unreleased:

```text
rediscloud_provider_source     = branch
rediscloud_provider_ref        = alan/agent-memory-terraform-provider
```

When `rediscloud_provider_source` is `branch`, the workflow checks out the
fixed Redis Cloud provider repository, builds the provider binary, and writes a
temporary Terraform CLI `dev_overrides` configuration that points
`RedisLabs/rediscloud` to that binary. This is intentionally a workflow-local
override; no generated provider binary or Terraform CLI config is committed.

If the provider branch lives in a private repository or fork, configure the
`REDISCLOUD_PROVIDER_CHECKOUT_TOKEN` repository secret with read access to that
repository.

Once the provider is official, set `rediscloud_provider_source` to `registry`
and rely on the version constraint in `stacks/agent-memory/versions.tf`. In
registry mode the branch/ref input is ignored.

The Redis Cloud Terraform provider also honors `REDISCLOUD_URL`. Use it only
for internal API environments; leave it unset for the public Redis Cloud API.
