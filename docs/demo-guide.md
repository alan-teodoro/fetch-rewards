# Redis Cloud configuration walkthrough

Complete [customer setup](customer-setup.md) first. Use
`configs/fetch-rewards/subscriptions/demo-ai-us-east-1.json` throughout.
It starts with one subscription, one database and `shopping-agent-memory`, using
platform-managed models. Review the account-specific values before deployment.

For each change below, commit and push the JSON, run **Redis Cloud Config Apply**
with the same `config_path` and `operation = apply`, then review the summary.
Keep the workflow's pinned provider defaults while Agent Memory is unreleased.
The [customer guide](customer-setup.md#run-the-pipeline) explains approvals,
deferred plans and replacement behavior.

## 1. Create

Apply the baseline and verify the subscription, database and one READY store.

## 2. Add another agent

Add this sibling beside `shopping_agent` inside `agent_memory_stores`, with a
comma after the existing object:

```json
"support_agent": {
  "mode": "managed",
  "name": "support-agent-memory",
  "database": "shared_agent_memory",
  "short_term_ttl_seconds": 43200,
  "long_term_ttl_seconds": 31536000,
  "extraction_cadence_seconds": 300,
  "summarization": {
    "enabled": true,
    "trigger_strategy": "event_count",
    "event_count": {
      "threshold": 20,
      "retain_count": 10
    }
  },
  "custom_memory_types": [],
  "api_keys": {
    "runtime": {
      "mode": "managed",
      "name": "support-agent-runtime",
      "secret_ref": "aws-secrets-manager:/fetch-rewards/demo/support-agent-memory/runtime"
    }
  }
}
```

Validate before committing:

```bash
python3 scripts/rediscloud_config.py validate \
  --config configs/fetch-rewards/subscriptions/demo-ai-us-east-1.json
```

The plan should add only the support store and its runtime key/validation
resources. Check the actual plan; after apply, verify two READY stores sharing
the database. `secret_ref` is metadata; generated keys are not automatically
published to a secret manager.

## 3. Update

Change `shopping_agent.short_term_ttl_seconds` from `86400` to `43200` and apply.
Verify an in-place update and the same store ID. Keep the map keys unchanged.

## 4. Reapply unchanged

Run apply again. Expect no changes and no deployment approval.

## 5. Remove the added agent

Remove `support_agent` from JSON and apply. Verify that only that store and its
key/validation resources are deleted; the original store, database and
subscription remain. Database omission follows the same rule after dependent
stores have been removed.

## 6. Clean up

Run **Redis Cloud Config Destroy** with the same `config_path`,
`confirm_destroy = true` and an empty `agent_memory_key`. Review the deletions.
Managed resources are removed; external resources and the backend remain.
Keep the configuration file until teardown completes.
