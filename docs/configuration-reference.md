# Configuration reference

One JSON file describes one subscription. Start from the complete example in
`configs/fetch-rewards/subscriptions/demo-ai-us-east-1.json`, copy it to the
customer's directory and remove the resources or optional settings you do not
need. Review billing, names, region, network CIDR and source IPs before running it.

The example contains demonstration values. It is not a production network policy.

## Editing and validation

The workspace includes a JSON Schema association for VS Code. Other editors can
use `schemas/rediscloud-config.schema.json`; an optional `$schema` property may
reference that local file. Validation does not fetch schema references from the
configuration or contact Redis Cloud.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/rediscloud_config.py validate \
  --config configs/fetch-rewards/subscriptions/demo-ai-us-east-1.json
```

The schema checks JSON types, required properties and unknown fields. The Python
resource modules check references and ownership rules. Terraform validates stack
inputs and produces the actual lifecycle plan. The API remains authoritative for
available models, regions, detector IDs, capacity and evolving service limits.

Schema defaults are documentation; Terraform applies omitted input defaults.
Strings such as `"false"` are not booleans. Durations in seconds must be positive
integers. Provider timeout strings use units, for example `30m`.

## Top-level properties

| Property | Meaning |
| --- | --- |
| `schema_version` | Configuration format, currently `1` |
| `customer`, `environment` | Descriptive labels; they do not select credentials or an approval environment |
| `subscription_key` | Durable state namespace; choose it once |
| `subscription` | Managed subscription or reference to an external subscription |
| `databases` | Map of database identities to configuration |
| `agent_memory_stores` | Map of Agent Memory identities to configuration |

Map keys contain lowercase letters, numbers, underscores or hyphens and have
2–64 characters. Resource display names are normalized to lowercase words
separated by hyphens, with 3–63 characters. Keep map keys stable when renaming a
display name. Moving a resource to another map key is a state migration.

## Subscription and databases

`subscription.mode` defaults to `managed`. Supply its name and the region,
deployment CIDR and billing selector appropriate for the account. The basic
stack accepts `AWS` or `GCP`; the reference lifecycle is qualified against AWS.
Active-Active and CMEK are not part of this configuration contract.

Use `subscription.creation_plan` for the initial capacity envelope:
`dataset_size_in_gb`, `throughput_ops_per_second`, `replication`,
`support_oss_cluster_api` and `modules`. Historical top-level capacity properties
remain accepted; the nested values take precedence. Do not specify both forms
for new configurations.

Each managed database requires a name. Its optional fields cover capacity, Redis
version, persistence, eviction, TLS, source IPs, alerts, remote backups and the
application ACL. Omit `redis_version` to use the service default. For Agent Memory,
enable TLS and the default database user; `agent_memory_compatible: true` enables
the default user when it was not explicitly set. Keep public endpoint access
enabled on the backing subscription as required by the current integration.

`source_ips` must include the service egress addresses supplied for the selected
Agent Memory region and any application addresses that need direct database
access. A public endpoint is not a reason to allow every source address.

`mode: external` preserves infrastructure owned elsewhere. An external
subscription can provide `subscription_id`; an external database can provide
`database_id`. This repository does not adopt existing resources automatically.
Changing a managed entry to external requires an explicit ownership transfer.

## Agent Memory

A managed store requires a name and either `database`, referring to a database
map key, or `database_id`, referring to an existing database. Prefer map references
when the database is described by the same file.

| Group | Inputs |
| --- | --- |
| Retention | `short_term_ttl_seconds`, `long_term_ttl_seconds` |
| Extraction | `extraction_cadence_seconds`, optional `extraction_strategy` |
| Models | `llm` and `embedding`, configured together for customer-managed models |
| Summarization | `enabled`, optional strategy and event-count settings |
| Memory types | List of named types, descriptions, fields and extraction prompts |
| Exclusions | Semantic policy, built-in detectors and custom regex detectors |
| Runtime keys | Named `api_keys` map; each entry can be enabled or disabled |
| Timeouts | Optional `create`, `read`, `update`, `delete` provider durations |

Each runtime key also accepts `create`, `read` and `delete` timeouts. A key's
`secret_ref` is metadata only; it does not publish the generated value. Store
`tags` are reserved metadata and are not applied to the API. They may be omitted.

For customer-managed models, put the GitHub secret's environment variable name
in `credentials.api_key_env_var`, never its value. The workflows expose
`AGENT_MEMORY_LLM_API_KEY` and `AGENT_MEMORY_EMBEDDING_API_KEY`. Increase
`credentials.api_key_version` whenever changing the secret. A secret change alone
does not create a Terraform diff for a write-only argument.

The JSON and stack inputs keep optional blocks as objects for readability. The
provider represents them as zero-or-one lists in state. The state adapter makes
that translation when an omitted resource must be destroyed; it rejects
ambiguous shapes rather than guessing and never copies stored model secrets.

## Changes and removal

Always inspect the plan. Supported updates preserve store identity; immutable
changes can replace the store and its keys. This includes changing its database
or a configured extraction strategy and removing or redefining existing custom
memory types. Exact replacement behavior belongs to the pinned provider.

Removing a managed store or database map entry produces a reviewed deletion
plan. Remove dependent store entries before deleting their database. Deleting the
whole JSON file does not tear infrastructure down: use Config Destroy first.

## Format upgrades and extensions

Compatible optional additions keep `schema_version: 1`. A breaking JSON contract
needs a new version and a documented migration. Terraform state schema changes
are separate from the JSON format and require an explicit upgrade rehearsal.

To expose another provider field, update the JSON Schema, its resource renderer,
Terraform variables/resource, example or guide and a lifecycle test together.
Keep resource behavior in Terraform and service-specific input handling in its
Python module. Do not copy the entire provider schema into a generic renderer.
