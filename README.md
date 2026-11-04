# Redis Cloud infrastructure from configuration

Manage Redis Cloud subscriptions, databases and Agent Memory through a versioned
JSON file and GitHub Actions. The same configuration defines creation, updates
and removal. Terraform owns the resources and stores one state per subscription JSON in private S3.
The deployment root passes parent IDs between modules, so Terraform orders both
creation and deletion. Python validates/renders inputs and manages plan approval;
it does not download, parse or edit state files.

## Start here

| Goal | Guide |
| --- | --- |
| Configure the customer's accounts, credentials and backend | [Customer setup](docs/customer-setup.md) |
| Understand the JSON and optional settings | [Configuration reference](docs/configuration-reference.md) |
| Operate the deployment and recover from failures | [Operations and recovery](docs/maintenance.md) |

After setup, use **Redis Cloud Config Apply** with `operation = plan`, review the
summary, then run `operation = apply`. Changed configurations require approval in
the configured GitHub environment. Unchanged runs need no approval.

## Working rules

- Keep `subscription_key` stable: it identifies the state. Database/store map keys
  identify module instances inside that state; renames require explicit migration.
- Remove a managed entry from JSON to propose its deletion. Remove dependent
  agents before removing their database.
- Use **Redis Cloud Config Destroy** for complete or selective teardown. Keep the
  JSON until teardown finishes; deleting a file does not delete infrastructure.
- Review replacements: they create new store IDs and keys without migrating
  application context. Deletion is not proof of physical data erasure.
- `mode = external` references infrastructure owned elsewhere. Switching existing
  managed resources to external requires explicit state reconciliation.

One repository uses one Redis Cloud account, backend and approval environment.
The JSON `customer` and `environment` fields are descriptive labels.

## Layout

```text
configs/<customer>/subscriptions/   Desired configuration for each subscription
schemas/                           JSON Schema and editor validation
stacks/deployment/                 Single root module and S3 backend
stacks/subscription/               Reusable subscription module
stacks/database/                   Reusable database/ACL module
stacks/agent-memory/               Reusable Agent Memory/key module
modules/terraform_state_backend/   One-time S3 and GitHub OIDC bootstrap
scripts/rediscloud_config.py        Validate/render configuration
scripts/rediscloud_review.py        Review and execute approved plans
scripts/rediscloud_auth_check.py    Check Redis Cloud access before planning
scripts/rediscloud/                 Implementation shared by those commands
tests/                             Maintained automation regressions
.github/workflows/                 Apply, destroy and validation workflows
```

## Local validation

Use Python 3.12+ and Terraform 1.16.7+. GitHub Actions pins its tool versions.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/rediscloud_config.py validate --config configs/fetch-rewards/subscriptions/demo-ai-us-east-1.json
terraform fmt -check -recursive
```

The **Terraform Validate** workflow also validates every stack and tests the
backend bootstrap with mocked AWS providers. The offline Terraform contract
tests are explained in the maintenance guide. Local regression tests use simulated
commands or synthetic state and do not create cloud infrastructure.

## Scope

The qualified deployment path is AWS, Pro single-region, databases with ACLs and
Agent Memory. Active-Active, customer-managed Redis Cloud encryption and private
connectivity need separate integration work. The default workflows install the
official Redis Cloud provider 2.20.0 from the Terraform Registry.

Generated passwords and runtime keys are sensitive state outputs. `secret_ref`
does not publish keys to a secret manager; store `tags` are reserved metadata.
Agree application secret delivery before deployment.
