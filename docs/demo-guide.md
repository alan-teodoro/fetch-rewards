# Redis Cloud configuration demo

## One configuration throughout the presentation

Use `configs/fetch-rewards/subscriptions/demo-ai-us-east-1.json` for every step.
It starts with one managed subscription, one shared database and one Agent
Memory named `shopping-agent-memory`. Other configurations under `configs/`
are internal development/QA scenarios. Former alternate demo examples and the
two-agent regression fixture live under `tests/fixtures/configs/`.

The main example includes TLS, network allowlists, database alerts, ACLs,
short/long-term TTL, summarization, extraction cadence, custom memory types,
memory exclusions and a runtime API key. Models are platform-managed, so this
example does not require separate LLM/embedding credentials.

Before using it in another account, review billing, region, CIDR and source IPs.
The included values match the demo account; customers must supply their own.
`secret_ref` records the intended secret destination; this repository does not
publish generated keys to Secrets Manager automatically.

The tested provider commit is:

```text
39d6752e915a71c7b58f7ee4b0f63304be3528df
```

Until its fixes are integrated and released, explicitly select this commit as
`rediscloud_provider_ref`, with `rediscloud_provider_source = branch`.

## 1. Create the baseline

Open **Actions > Redis Cloud Config Apply**, select the branch containing your
configuration commit and set:

```text
config_path = configs/fetch-rewards/subscriptions/demo-ai-us-east-1.json
operation = apply
rediscloud_provider_source = branch
rediscloud_provider_ref = 39d6752e915a71c7b58f7ee4b0f63304be3528df
```

Review the run summary before approving `dev`. Fresh creation shows the
subscription plan and the inventory of dependent resources. Database and Agent
Memory plans are generated after their dependencies exist. One approval covers
the frozen configuration and those explicitly deferred steps. Failure stops
later steps; completed changes remain managed in Terraform state.

Show the resulting subscription, database and the single READY agent.

## 2. Add a second agent to the same file

Add the following sibling entry beside `shopping_agent` inside
`agent_memory_stores`. Insert a comma after the existing shopping-agent object.
This is a fragment of the same configuration, not another configuration file.

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

Validate, commit and push the edited JSON:

```bash
python3 scripts/rediscloud_config.py validate \
  --config configs/fetch-rewards/subscriptions/demo-ai-us-east-1.json
```

Run the same apply workflow. With an unchanged baseline, the review should show
only the second agent stack being created: its store, runtime key and two
Terraform validation resources. The subscription, database and shopping agent
should have no changes. Review the actual plan rather than assuming this result.
After approval, show two READY agents sharing the same database.

## 3. Update a setting

Change `shopping_agent.short_term_ttl_seconds` from `86400` to `43200`, commit
and push. Run apply again. Show the in-place Agent Memory update and confirm
that the store ID stays the same. Keep map keys such as `shopping_agent` stable:
they identify Terraform state paths, not display labels.

## 4. Show an unchanged run

Run apply with the same configuration. All stacks should report no changes and
no deployment approval should be requested.

## 5. Delete the second agent: current implementation

The current runner does not discover resources omitted from the JSON. Removing
an entry alone leaves its separate state and live resources intact. Desired-state
reconciliation for omitted entries is not implemented yet.

For the currently supported deletion flow, keep `support_agent` in the file,
run **Redis Cloud Config Destroy** with the same configuration/provider and:

```text
agent_memory_key = support_agent
confirm_destroy = true
```

Review and approve the deletion plan. The shopping agent, shared database and
subscription must be preserved. After successful deletion, remove the
`support_agent` entry from the JSON and commit it. Applying before removing
that entry would recreate the agent.

## 6. Full cleanup

Use Config Destroy with the same configuration, `confirm_destroy = true` and
an empty `agent_memory_key`. Review every deletion before approving. This
removes managed agents, database/ACLs and subscription in dependency order;
external resources and the state backend are retained. Do this only when the
presentation environment is no longer needed.

## Validation evidence

The provider's planned technical matrix passed; maintainer review, integration
and release remain pending. Detailed evidence and historical run links are in
[the internal validation history](internal/demo-validation-history.md).
The QA cleanup requested before this demo completed successfully in
[run 38770072079](https://github.com/alan-teodoro/fetch-rewards/actions/runs/38770072079);
API verification confirmed the QA subscription, databases and stores absent.
This preparation did not provision a new demo environment.
