# Demo Guide

Use this guide to present the config-driven Redis Cloud and Agent Memory PoC.
The goal of the demo is to show that infrastructure can be reviewed as a JSON
desired-state file, applied through GitHub Actions, and evolved safely over
time.

## Demo Story

1. Show the config file.
   - Open `configs/fetch-rewards/subscriptions/demo-lifecycle-us-east-1.json`.
   - Start with one Agent Memory service, then add the second service using
     the example below.
   - Point out that one subscription can contain one or more databases and one
     or more Agent Memory services.
   - Show that multiple Agent Memory services can reference the same database
     with the stable database key.

2. Explain resource ownership.
   - `mode = "managed"` means Terraform creates and updates the resource.
   - `mode = "external"` means the resource already exists and is referenced by
     ID or name.
   - Stable map keys such as `shared_agent_memory` and `shopping_agent` drive
     state paths and should be treated as durable IDs.

3. Show secret handling.
   - Redis Cloud account API keys are GitHub secrets.
   - The default demo uses platform-managed Agent Memory models. If a config
     uses customer-managed LLM and embedding models, their credentials are
     referenced by env var name, for example `AGENT_MEMORY_LLM_API_KEY`.
   - Agent Memory data-plane API keys are different from Redis Cloud account
     API keys. Terraform marks them sensitive and does not print them.

4. Run `plan`.
   - Use **Actions > Redis Cloud Config Apply > Run workflow**.
   - Select the branch containing the config and workflow changes. While PR #2
     is open, select `feature/agent-memory-config-driven`.
   - Set `config_path` to the demo config or to the customer-specific config.
   - Set `operation = plan`.
   - Review the GitHub Actions summary before apply.
   - A fresh creation plan skips stacks whose dependencies are being created,
     replaced, or renamed. Once the dependencies exist, plan includes the
     database and Agent Memory stacks even when their mode remains `managed`.

5. Run `apply`.
   - Set `operation = apply` only after the plan summary looks correct.
   - Approve the `dev` environment checkpoint.
   - This checkpoint approves execution before the workflow creates its plans.
   - The workflow applies by dependency phase: subscription, databases, then
     Agent Memory.
   - Each phase is planned before any saved plan in that phase is applied.

6. Show the result.
   - In Redis Cloud, show the subscription, database, and Agent Memory service.
   - In the Actions summary, show the state keys, plan counts, and runtime notes.

7. Show maintenance through the same config.
   - Change a database alert threshold and an Agent Memory policy using the
     example below.
   - Validate the JSON, commit and push it to the demo branch, then run the
     workflow against that branch and the same `config_path`.
   - Compare resource IDs before and after the update. Repeat apply without
     changing the config to check that every stack reports no changes.

8. Delete one service.
   - Run **Redis Cloud Config Destroy** with the same config file,
     `agent_memory_key = support_agent`, and `confirm_destroy = true`.
   - Approve the `dev` checkpoint. Confirm that only the support agent and its
     data-plane keys were destroyed; the shopping agent and backing resources
     keep their IDs.
   - Remove `support_agent` from the JSON after the destroy run succeeds,
     commit it, and run plan again. Keeping the entry would recreate it on apply.

9. Explain complete cleanup.
   - An empty `agent_memory_key` targets all managed resources in the file,
     in reverse dependency order. Use this after the demo for complete cleanup.
   - Re-adding a deleted service to the JSON and applying creates a new store.

## Lifecycle Rehearsal Matrix

Use the isolated `demo-lifecycle-us-east-1.json` config for live tests. Its
subscription is `fetch-demo-lifecycle`, database is `agent-memory-demo-db`,
and every managed state lives under `subscriptions/demo-lifecycle-us-east-1/`.
Use one provider commit throughout the rehearsal and demo.

| Scenario | Expected result |
| --- | --- |
| Fresh plan | Subscription creation is previewed; missing downstream dependencies are reported as skipped. |
| Fresh apply with one service | One subscription, one database with ACL resources, and one Agent Memory service with a runtime key are created. |
| Plan with existing managed dependencies | Subscription, database, and Agent Memory all appear in the plan. |
| Add a second service | Only the new Agent Memory stack is created; existing resource IDs are preserved. |
| Update database alert, memory TTL, and extraction cadence | Relevant resources update in place; IDs are preserved. |
| Reapply unchanged | All stacks report no changes. |
| Delete only the second service | Its store and runtime keys disappear; the first service, database, and subscription remain. |
| Remove the deleted entry and plan | No unintended recreation or changes to remaining resources. |
| Re-add the deleted entry | A new service is created using the same durable state key. |
| Existing subscription, new database and service | The subscription is preserved through apply and cleanup. |
| Existing subscription and database, new service | Only the Agent Memory stack is managed and removed. |
| Full cleanup | Services and keys are destroyed before databases and subscription. |
| Invalid selector or external deletion target | The request fails before approval and destruction. |
| Agent Memory replacement in apply | The guard stops the Agent Memory phase before any of its plans are applied. |

Local regression tests execute the actual workflow shell with a simulated
Terraform CLI to check phase ordering, state selection, and destructive guards:

```bash
python3 -m unittest discover -s tests -v
```

These checks supplement live Actions runs. Record the real run URLs and
resource IDs before marking a lifecycle scenario as passed.

## Add a Second Agent Memory

Add this entry to `agent_memory_stores` beside `shopping_agent` in the same
lifecycle config, validate, commit and push, then run plan and apply:

```json
"support_agent": {
  "mode": "managed",
  "name": "support-agent-demo",
  "database": "shared_agent_memory",
  "short_term_ttl_seconds": 86400,
  "long_term_ttl_seconds": 7776000,
  "extraction_cadence_seconds": 300,
  "summarization": {
    "enabled": true,
    "trigger_strategy": "event_count",
    "event_count": { "threshold": 30, "retain_count": 12 }
  },
  "api_keys": {
    "runtime": {
      "mode": "managed",
      "name": "support-agent-demo-runtime",
      "secret_ref": "aws-secrets-manager:/fetch-rewards/demo/lifecycle/support/runtime"
    }
  }
}
```

Each service has a separate state and keys while sharing the same database.
Use additional stable map keys to add more services with this pattern.

## Presentation Timing

| Time | Show | Customer takeaway |
| --- | --- | --- |
| 0-3 minutes | JSON, resource references, stable keys, and secrets by reference | Desired infrastructure is versioned in configuration files. |
| 3-6 minutes | Actions inputs, approval, dependency phases, and plan summary | The customer runs the same automation for creation and maintenance. |
| 6-9 minutes | Subscription, database, and Agent Memory in Redis Cloud | The configuration maps to actual resources with separate Terraform states. |
| 9-13 minutes | A reviewed config change and the recorded update run | Routine changes use the same JSON file and workflow. |
| 13-15 minutes | Unchanged reapply, cleanup, and PoC limits | The customer can verify convergence and explicitly control cleanup. |

Rehearse provisioning beforehand and keep the successful run links available.
Use the live run status and recorded results if provisioning takes longer than
the presentation slot.

## Configuration Maintenance Example

Use `demo-lifecycle-us-east-1.json` for the one-service baseline, then add the
second service. `demo-ai-us-east-1.json` is the larger two-service reference.
The playground config uses an external `fetch-demo-ai`
subscription, which must already exist.

After the baseline apply, edit these values in the same demo file:

| JSON location | Baseline | Example update |
| --- | --- | --- |
| `databases.shared_agent_memory.alerts` entry named `dataset-size`, field `value` | `80` | `75` |
| `agent_memory_stores.shopping_agent.short_term_ttl_seconds` | `86400` | `172800` |
| `agent_memory_stores.shopping_agent.extraction_cadence_seconds` | `300` | `120` |

These are candidates for updates in place. Confirm the actual plans during the
rehearsal: the database and shopping-agent plans should contain updates, with
no deletes or replacements; the subscription and support-agent plans should
contain no changes. Check that the database ID and Agent Memory store IDs are
preserved, then repeat apply unchanged to verify convergence.

Keep `subscription_key`, `shared_agent_memory`, and `shopping_agent` unchanged.
They identify state and references. Changing a config filename alone does not
create a new state namespace, but changing `subscription_key` does. Existing
resources require import before a new state can manage them.

GitHub Actions reads committed files from the selected branch. Local JSON
edits and the local `.env` do not update the files or secrets used by Actions.
The customer maintenance flow is: edit JSON, validate, review the diff, commit
and push, then run the workflow against that revision.

Keep resource ownership as `managed` during maintenance. Plan can preview
updates once the existing dependency names are available. In apply mode, the
workflow produces and applies saved plans per phase. It does not pause for
another approval after those plans are created.

## Pre-Demo Checklist

- Remote Terraform state is bootstrapped with `stacks/state-backend`.
- GitHub variables are configured:
  - `TF_STATE_BUCKET`
  - `TF_STATE_REGION`
  - `AWS_GITHUB_ACTIONS_ROLE_ARN`
- Redis Cloud secrets are configured:
  - `REDISCLOUD_ACCESS_KEY`
  - `REDISCLOUD_SECRET_KEY`
- Leave `REDISCLOUD_URL` unset for the public Redis Cloud API. Set it only
  when intentionally targeting a non-public Redis Cloud API endpoint.
- If using customer-managed models, configure:
  - `AGENT_MEMORY_LLM_API_KEY`
  - `AGENT_MEMORY_EMBEDDING_API_KEY`
- Until the official Terraform provider includes Agent Memory resources, keep
  the config workflow provider source set to `branch`. The workflow builds the
  Agent Memory provider branch before running Terraform.
- Record the exact provider commit used for the rehearsal. The
  `rediscloud_provider_ref` input accepts a commit SHA; reuse it for the demo
  and cleanup so a moving branch does not change the provider between runs.
- Rehearse from an empty demo state: create the subscription, database, and
  Agent Memory services, apply the maintenance example, and reapply unchanged.
  Record the run URLs, resource IDs, timings, and any unexpected changes.
- Keep the demo resources available for the presentation. The destroy workflow
  removes all managed resources in the selected config, including the
  subscription when its mode is `managed`.
- Confirm the database `source_ips` against the current Agent Memory endpoint
  egress IPs during rehearsal. The checked-in demo list reflects the previous
  test environment and should be reviewed for the selected target.

## Local Dry Run

Validate all config files:

```bash
for config in configs/fetch-rewards/subscriptions/*.json; do
  python3 scripts/rediscloud_config.py validate --config "$config"
done
```

Render the demo config:

```bash
python3 scripts/rediscloud_config.py render \
  --config configs/fetch-rewards/subscriptions/demo-ai-us-east-1.json \
  --out-dir .generated/rediscloud/demo-ai-us-east-1
```

Render configs that use customer-managed models only when the model-provider
secrets are available:

```bash
export AGENT_MEMORY_LLM_API_KEY="<model-provider-api-key>"
export AGENT_MEMORY_EMBEDDING_API_KEY="<embedding-provider-api-key>"

python3 scripts/rediscloud_config.py render \
  --config configs/fetch-rewards/subscriptions/<config-with-customer-managed-models>.json \
  --out-dir .generated/rediscloud/customer-managed-models
```

The generated files under `.generated/` are runtime artifacts and should not be
committed.

## Safe Demo Defaults

- Start with `operation = plan`.
- Use `external` mode for customer resources that already exist and should not
  be managed by this PoC.
- Do not remove a resource from JSON expecting Terraform to destroy it. The PoC
  intentionally avoids implicit deletes from config removal.
- Use **Redis Cloud Config Destroy** with the same `config_path` and
  `confirm_destroy = true` for intentional cleanup.

## Current PoC Limits

- A fresh plan skips stacks whose dependencies are being created, replaced,
  or renamed. Existing managed dependencies support downstream plan previews.
- The config-driven apply workflow creates and updates resources. The separate
  config-driven destroy workflow cleans up managed resources from the same JSON
  file after explicit confirmation and environment approval.
- Publishing generated Agent Memory data-plane API keys to the referenced
  `secret_ref` is still a follow-up step.
- While Agent Memory support is not in the official Redis Cloud Terraform
  provider, demos that use Agent Memory should run with
  `rediscloud_provider_source = branch`.
- During the Agent Memory public preview, use an eligible Redis Cloud database
  with public endpoint access and the default user enabled.

## Preparation Evidence — October 14, 2026

The demo is scheduled for October 15. The following evidence establishes the
current baseline; it does not replace a fresh create/update/reapply rehearsal.

- [Terraform validation of the current commit, October 9](https://github.com/alan-teodoro/fetch-rewards/actions/runs/37981190429)
  passed on commit `9c44806457974a977f4b3ba90a66ca278d4d9ada`.
- [Fresh demo plan, October 14](https://github.com/alan-teodoro/fetch-rewards/actions/runs/38614196232)
  passed against the same repository commit and provider commit
  `a0c7d29254b6f2f115bbe1e454d2926fbe5a678e`. Redis Cloud authentication,
  AWS OIDC, and state-prefix access succeeded. The subscription stack planned
  two creations: the subscription and its Terraform validation resource, with
  no updates or deletes. Database and Agent Memory plans were skipped because
  their dependencies are managed. This run did not create infrastructure.
  It predates the dependency-aware plan correction and selective destroy input.
- [Successful demo apply, October 9](https://github.com/alan-teodoro/fetch-rewards/actions/runs/37977388805)
  used `demo-ai-us-east-1.json` and provider commit
  `a0c7d29254b6f2f115bbe1e454d2926fbe5a678e`. It reused the subscription,
  updated the database, and created the two Agent Memory services. It was not
  a complete fresh-create test.
- [Successful cleanup, October 9](https://github.com/alan-teodoro/fetch-rewards/actions/runs/37980375505)
  destroyed both Agent Memory stacks, the database stack, and the subscription
  stack using the same config and provider commit.
- Local Terraform formatting and all four stack validations passed on
  October 14. Agent Memory validation used a freshly compiled local provider
  from commit `1c0b452`, with the expected development-override warning.
- All five versioned configs passed validation and rendering. Rendering used
  dummy model credentials, verified isolated state keys and secret-free
  manifests, and enabled the default user for compatible managed databases.
- Negative config checks rejected a disabled default user, an unknown database
  reference, missing public endpoint access, a literal secret, an unsupported
  alert, and an invalid state key.
- The required backend variable names, Redis Cloud secret names, and the
  `dev` environment reviewer checkpoint were present in GitHub. Local Redis
  Cloud public and QA credentials returned HTTP 200 on read-only subscription
  queries; neither target returned subscriptions at preparation time.
