# Redis Cloud infrastructure from configuration

Create and maintain Redis Cloud subscriptions, databases and Agent Memory stores with Terraform and GitHub Actions. Customers edit a versioned JSON file and run a workflow; the same file defines subsequent updates and deletions.

## Start here

1. Follow [customer setup](docs/customer-setup.md) to configure the encrypted state backend, Redis Cloud credentials and GitHub environment.
2. Use [the complete Fetch example](configs/fetch-rewards/subscriptions/demo-ai-us-east-1.json). For another customer, copy it to `configs/<customer>/subscriptions/<name>.json` and adjust billing, names, region, CIDR and source IPs.
3. Run **Redis Cloud Config Apply** with `operation = plan` to inspect the changes.
4. Run it with `operation = apply` and review the plan summary before approving the environment deployment.

The [walkthrough](docs/demo-guide.md) shows how to add another agent to the same configuration.

## Daily operations

| Goal | Action |
| --- | --- |
| Create or update infrastructure | Edit the JSON, commit, then run Config Apply. |
| Add another agent or database | Add another map entry with a new, durable key. |
| Delete an agent or database | Remove its JSON entry and run Config Apply; deletion appears in the review. Remove dependent agents before deleting their database. |
| Replace a store after an immutable change | Review Terraform's replacement plan. The replacement receives a new store ID and keys; context is not migrated automatically. |
| Delete everything managed by a configuration | Run Config Destroy with `confirm_destroy = true`. |
| Delete only one store | Run Config Destroy with its `agent_memory_key`. Remove its JSON entry too if it must stay deleted. |
| Use existing infrastructure | Set `mode = external`; externally owned resources are not created or destroyed. |

Removing the entire file does not execute a workflow. Keep `subscription_key` and resource map keys stable: they identify Terraform state. Renaming a key requires an explicit state migration.

## How execution works

One configuration represents one subscription. Creation follows subscription → databases → Agent Memory. Deletion runs in reverse order. States are isolated under `subscriptions/<subscription_key>/` in private, encrypted S3 storage.

The workflow generates saved plans and a readable summary before one environment approval. New dependencies can defer downstream plans until those dependencies exist; the summary identifies these steps. Approval covers the pinned configuration, including those deferred plans. An unchanged run needs no approval. Failures stop further work; completed operations are not automatically rolled back.

Reviewed plans, frozen inputs and the exact development provider binary are kept in an encrypted bundle. They expire after one hour. Plan files and state can contain secrets; summaries omit secret values. See [execution details](docs/config-driven-architecture.md).

## Repository layout

```text
configs/<customer>/subscriptions/   Customer desired-state JSON files
stacks/subscription/               Pro subscription
stacks/database/                   Database and ACLs
stacks/agent-memory/               Store and data-plane API keys
stacks/state-backend/              One-time S3 and GitHub OIDC bootstrap
modules/terraform_state_backend/   Reusable backend module
scripts/rediscloud_config.py        Configuration command
scripts/rediscloud_review.py        Reviewed execution command
scripts/rediscloud/                 Resource inputs and execution modules
scripts/internal/                  Provider engineering test tools
.github/workflows/                 Apply, destroy, validation and internal tests
docs/                              Customer guides and architecture
tests/fixtures/configs/             Historical QA and regression configurations
```

Terraform stacks contain resource behavior. Python renders JSON into Terraform inputs and coordinates isolated states. GitHub Actions supplies credentials and the review/approval steps. Redis Cloud resources stay organized by service; AWS state storage is independent of the Redis Cloud hosting provider.

## Validation

Use Terraform **1.11.1 or newer** and Python **3.12 or newer** for local helpers. The workflow pins its Terraform and provider versions. Agent Memory currently requires the unreleased provider build; keep `rediscloud_provider_source = branch` until an official release includes these resources.

```bash
terraform fmt -check -recursive
python3 -m unittest discover -s tests -v
python3 scripts/rediscloud_config.py validate --config configs/fetch-rewards/subscriptions/demo-ai-us-east-1.json
```

**Terraform Validate** checks the configuration, tests and all stacks, including Agent Memory with the pinned provider. **Internal Provider Validation** contains opt-in provider engineering scenarios and is not part of routine customer operations.

## Current scope

The current subscription stack supports the Pro single-region layout; do not interpret the JSON as support for Active-Active, customer-managed encryption keys or all networking combinations. Those require dedicated stack/schema work and lifecycle tests. Future Iris services should follow the same service-stack and durable state-key conventions.

`secret_ref` and Agent Memory `tags` are metadata only: this project does not publish keys to a secret manager or apply store tags. Generated data-plane keys are sensitive Terraform outputs stored in encrypted state. Customer-managed model keys use write-only provider inputs; changing a secret also requires increasing `credentials.api_key_version`.
