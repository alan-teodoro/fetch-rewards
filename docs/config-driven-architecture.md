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
  qa-agent-memory-byo-models-us-east-1.json
  qa-agent-memory-smoke-us-east-1.json
```

Use one file per subscription. The `environment` field can be `dev`, `prod`, or
any customer-specific environment label. This allows multiple dev or prod
subscriptions without changing the runner. Production files should follow the
same pattern once the customer confirms names, regions, billing, and networking.

The checked-in `demo-ai-us-east-1.json` file is intentionally verbose. It shows
every configuration key currently supported by the subscription, database, and
Agent Memory Terraform stacks. Customers can use it as the demo input and then
remove unused fields as their production config stabilizes.

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

Removing a resource from the config file does not automatically destroy it. This
is intentional for the PoC, especially for Agent Memory data. Destructive flows
should use an explicit destroy workflow or a future `desired_state = "absent"`
contract with approval.

## Stable Keys

Map keys such as `shared_agent_memory` and `shopping_agent` are stable internal
identities. They are used for state paths and references. Resource names can
change over time, but changing a stable key should be treated as a migration.

Example state layout:

```text
subscriptions/dev-ai-us-east-1.tfstate
databases/dev-ai-us-east-1/shared_agent_memory.tfstate
agent-memory/dev-ai-us-east-1/shopping_agent.tfstate
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
Memory. In `apply` mode, every stack in a phase is planned before any saved plan
from that phase is applied. In `plan` mode, downstream managed stacks are
skipped when they depend on a managed resource that does not exist yet.

## Local Agent Memory Provider

Until Agent Memory support is available in the official Redis Cloud Terraform
provider release, use a Terraform CLI provider override on machines that run the
Agent Memory stack.

Example `~/.terraformrc`:

```hcl
provider_installation {
  dev_overrides {
    "RedisLabs/rediscloud" = "/Users/alan/workspaces/alan-teodoro/redis-terraform/terraform-provider-rediscloud/bin"
  }

  direct {}
}
```

The override path must contain the locally built provider binary. Once the
provider is official, remove the override and rely on the version constraint in
`stacks/agent-memory/versions.tf`.

The Redis Cloud Terraform provider also honors `REDISCLOUD_URL`. Use it only
for QA or internal API environments; leave it unset for the public Redis Cloud
API.

When using a local provider build in GitHub Actions, run the workflow on a
runner that has the provider binary. Configure `REDISCLOUD_RUNNER` with that
runner label and `REDISCLOUD_PROVIDER_DEV_OVERRIDE_DIR` with the provider
binary directory. With the official provider release, remove both variables.
