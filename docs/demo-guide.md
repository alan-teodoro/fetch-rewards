# Demo Guide

Use this guide to present the config-driven Redis Cloud and Agent Memory PoC.
The goal of the demo is to show that infrastructure can be reviewed as a JSON
desired-state file, applied through GitHub Actions, and evolved safely over
time.

## Demo Story

1. Show the config file.
   - Open `configs/fetch-rewards/subscriptions/demo-ai-us-east-1.json`.
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
   - Customer-managed LLM and embedding credentials are referenced by env var
     name, for example `AGENT_MEMORY_LLM_API_KEY`.
   - Agent Memory data-plane API keys are different from Redis Cloud account
     API keys. Terraform marks them sensitive and does not print them.

4. Run `plan`.
   - Use **Actions > Redis Cloud Config Apply > Run workflow**.
   - Set `config_path` to the demo config or to the customer-specific QA config.
   - Set `operation = plan`.
   - Review the GitHub Actions summary before apply.

5. Run `apply`.
   - Set `operation = apply` only after the plan summary looks correct.
   - The workflow applies by dependency phase: subscription, databases, then
     Agent Memory.
   - Each phase is planned before any saved plan in that phase is applied.

6. Show the result.
   - In Redis Cloud, show the subscription, database, and Agent Memory service.
   - In the Actions summary, show the state keys, plan counts, and runtime notes.

## Pre-Demo Checklist

- Remote Terraform state is bootstrapped with `stacks/state-backend`.
- GitHub variables are configured:
  - `TF_STATE_BUCKET`
  - `TF_STATE_REGION`
  - `AWS_GITHUB_ACTIONS_ROLE_ARN`
- Redis Cloud secrets are configured:
  - `REDISCLOUD_ACCESS_KEY`
  - `REDISCLOUD_SECRET_KEY`
- If using QA credentials, also configure:
  - `REDISCLOUD_ACCESS_KEY_QA`
  - `REDISCLOUD_SECRET_KEY_QA`
  - `REDISCLOUD_URL_QA`
- If using customer-managed models, configure:
  - `AGENT_MEMORY_LLM_API_KEY`
  - `AGENT_MEMORY_EMBEDDING_API_KEY`
- Until the official Terraform provider includes Agent Memory resources, run on
  a runner that has the local provider binary and configure:
  - `REDISCLOUD_RUNNER`
  - `REDISCLOUD_PROVIDER_DEV_OVERRIDE_DIR`

## Local Dry Run

Validate all config files:

```bash
for config in configs/fetch-rewards/subscriptions/*.json; do
  python3 scripts/rediscloud_config.py validate --config "$config"
done
```

Render the demo config:

```bash
export AGENT_MEMORY_LLM_API_KEY="<model-provider-api-key>"
export AGENT_MEMORY_EMBEDDING_API_KEY="<embedding-provider-api-key>"

python3 scripts/rediscloud_config.py render \
  --config configs/fetch-rewards/subscriptions/demo-ai-us-east-1.json \
  --out-dir .generated/rediscloud/demo-ai-us-east-1
```

The generated files under `.generated/` are runtime artifacts and should not be
committed.

## Safe Demo Defaults

- Start with `operation = plan`.
- Keep `allow_agent_memory_destroy = false`.
- Use `external` mode for customer resources that already exist and should not
  be managed by this PoC.
- Do not remove a resource from JSON expecting Terraform to destroy it. The PoC
  intentionally avoids implicit deletes from config removal.

## Current PoC Limits

- The config-driven workflow can create and update resources. Config-driven
  destroy is intentionally not automated yet.
- Publishing generated Agent Memory data-plane API keys to the referenced
  `secret_ref` is still a follow-up step.
- While Agent Memory support is not in the official Redis Cloud Terraform
  provider, demos that use Agent Memory require the local provider override.
- During the Agent Memory public preview, use an eligible Redis Cloud database
  with public endpoint access and the default user enabled.
