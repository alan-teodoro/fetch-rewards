# Configuration reference

One JSON file describes one subscription. Start from
`configs/fetch-rewards/subscriptions/demo-ai-us-east-1.json`. The JSON Schema in
`schemas/rediscloud-config.schema.json` supplies editor hints through the included
VS Code settings. An optional `$schema` property can reference that local file;
the validator does not fetch schemas or contact Redis Cloud.

```bash
python scripts/rediscloud_config.py validate --config configs/fetch-rewards/subscriptions/demo-ai-us-east-1.json
```

Schema checks cover types, required properties and unknown fields. Python checks
references/ownership; Terraform produces the lifecycle plan. The API validates
available models, detector IDs, regions, capacity and evolving service limits.

## Identity and ownership

| Property | Meaning |
| --- | --- |
| `schema_version` | Format version, currently `1` |
| `customer`, `environment` | Labels; do not select credentials or approval environment |
| `subscription_key` | Selects `subscriptions/<key>/terraform.tfstate` |
| `subscription` | Managed subscription or external reference |
| `databases` | Map of database identities to settings |
| `agent_memory_stores` | Map of store identities to settings |

Map keys contain lowercase letters, digits, underscores or hyphens and have 2–64
characters. Display names normalize to lowercase, hyphen-separated names with
3–63 characters. Keep keys stable when changing display names.

`mode: managed` creates/owns a resource. `mode: external` references infrastructure
owned elsewhere. External subscriptions can supply `subscription_id`; external
databases can supply `database_id`. This project does not import automatically.
Changing a managed entry to external needs explicit state reconciliation.

## Subscription and databases

For a managed subscription, supply its name, region, deployment CIDR and billing
selector. Set `payment_method_id` or card type/last four for credit-card billing;
marketplace billing has its own selector. The stack accepts AWS or GCP, while the
reference lifecycle is qualified against AWS Pro single-region.

Use `subscription.creation_plan` for initial capacity: `dataset_size_in_gb`,
`throughput_ops_per_second`, `replication`, `support_oss_cluster_api` and `modules`.
Historical top-level capacity properties remain accepted; nested values take
precedence. Use the nested form in new files. Do not specify modules for Redis 8+.

A managed database requires a name. Optional settings cover size, throughput,
Redis version, persistence, eviction, TLS, source IPs, alerts, remote backups,
tags and its application ACL. Omit `redis_version` for the service default.
Database names must be unique across managed subscriptions in the same account
because application ACL names derive from them.

For Agent Memory, enable TLS, the default database user and public endpoint access
on the subscription as required by the integration. `agent_memory_compatible: true`
enables the default user when it is not explicitly supplied. The source-IP list
must include the service egress addresses for the region and any required direct
application access; confirm them before deploying.

## Agent Memory inputs

A managed store needs a name and either `database` (a database map key) or
`database_id` (an existing database), never both. Prefer map references for
databases described in the same file.

| Group | Inputs |
| --- | --- |
| Retention | `short_term_ttl_seconds`, `long_term_ttl_seconds` |
| Extraction | `extraction_cadence_seconds`, optional `extraction_strategy` |
| Models | `llm` and `embedding`, supplied together for BYO models |
| Summarization | `enabled`, optional strategy and event-count threshold/retain count |
| Memory types | Named types, descriptions, structured fields and extraction strategies |
| Exclusions | Semantic guidance, built-in detectors and custom regex detectors |
| Runtime keys | Named `api_keys` map with optional name, enabled flag and timeouts |
| Timeouts | Provider durations for `create`, `read`, `update`, `delete`, such as `30m` |

Second-based values must be positive integers. Timeouts are operation budgets,
not retention periods. Store `tags` and key `secret_ref` are metadata only; they
do not apply store tags or publish secrets.

### Optional objects and switches

The JSON and Terraform inputs use objects for optional policies and lists for
repeated fields/detectors. Terraform `dynamic` blocks translate these into the
provider's nested blocks. The provider manages the stored representation of those blocks. Resource removal
is represented by Terraform's native plan; no Python state adapter is needed.

| Input | Stack behavior |
| --- | --- |
| Omit an optional object or set it null | Emit no corresponding block |
| Supply an object with `enabled: false` | Emit a block with an explicit off flag |
| Omit a property declared `optional(bool)` | Keep null for the provider to resolve |
| Omit a property declared `optional(bool, true)` | Use true |
| Omit a detector list with default `[]` | Configure zero entries |

These are input semantics; removing a block is not a promise to reset an existing
remote setting. Use explicit switches when disabling and inspect the plan.
Schema defaults document intent; the input/provider contracts apply defaults.
Strings such as `"false"` are not booleans.

### Models and keys

Omit both model blocks for platform-managed models. For BYO models, choose
provider/model values supported by the service and supply both blocks at creation.
The following properties go inside a store; names shown are examples:

```json
"llm": {
  "provider": "openai",
  "model": "gpt-4o-mini",
  "credentials": {
    "api_key_env_var": "AGENT_MEMORY_LLM_API_KEY",
    "api_key_version": 1
  }
},
"embedding": {
  "provider": "openai",
  "model": "text-embedding-3-small",
  "credentials": {
    "api_key_env_var": "AGENT_MEMORY_EMBEDDING_API_KEY",
    "api_key_version": 1
  }
}
```

Use the GitHub secrets' environment-variable names, never their values. BYO
embedding also needs explicit `long_term_ttl_seconds`. Model keys are write-only
in provider state. Changing a key alone creates no diff: update the GitHub secret
and increase the positive integer `api_key_version` (default 1).

Runtime keys are different resources. Setting a key's `enabled` flag false removes
it from desired state and revokes an existing key on apply; it is not a pause.
For rotation, create/deliver/test another named key before removing the old one.
Generated keys remain sensitive state outputs; secret delivery is customer-owned.

### Exclusions

The policy has one master switch and three independently optional families.
Detector families and individual detectors have their own switches. Configure
all applicable flags explicitly when enabling a rule.

| Family | Purpose |
| --- | --- |
| `semantic` | Advisory extraction prompt; supply a prompt when enabled |
| `built_in_detectors` | Select service detectors by `id` |
| `custom_detectors` | Named application patterns with a regex matcher |

`redact` requests redaction of a match; `drop` requests dropping the matching
memory. An omitted action delegates its default to the provider/API. Semantic
guidance does not guarantee exclusion. Rules apply to newly extracted long-term
memories, not session events, summaries, direct application writes or existing
records. They are not a general input sanitizer and do not guarantee that
sensitive text cannot reach a model provider.

This property goes inside a managed store:

```json
"long_term_memory_exclusions": {
  "enabled": true,
  "semantic": {
    "enabled": true,
    "prompt": "Do not extract credentials, access tokens or recovery codes."
  },
  "built_in_detectors": {
    "enabled": true,
    "detectors": [
      { "id": "email", "enabled": true, "action": "redact" }
    ]
  },
  "custom_detectors": {
    "enabled": true,
    "detectors": [
      {
        "name": "fetch_account_id",
        "enabled": true,
        "action": "redact",
        "matcher": {
          "kind": "regex",
          "regex": { "pattern": "FR-[0-9]{8}" }
        }
      }
    ]
  }
}
```

The custom pattern describes `FR-` followed by eight digits. In `.tfvars`, assign
the same object using `long_term_memory_exclusions = { ... }`; in `variables.tf`,
`bool` and `string` declare types rather than sample values. The commented stack
example shows the direct Terraform form.

## Updates and removal

Always inspect the plan. Supported updates preserve identity; immutable changes
can replace the store and its keys. Examples include changing its database or a
configured extraction strategy, removing/redefining an existing custom type, or
removing its extraction strategy. The pinned provider determines the actual plan.

Remove a managed store/database entry to propose deletion. Remove dependent
stores before removing their database. Deleting the JSON itself performs no
teardown. Changing map keys requires migration rather than an ordinary rename.

For extensions, update schema, renderer, stack and regression coverage together.
Breaking JSON contracts require a schema-version migration. Provider state
upgrades are separate; see [maintenance](maintenance.md).
