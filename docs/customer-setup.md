# Customer setup

Use a separate repository, Redis Cloud account credentials and private state
backend for the customer's deployment. Copy versioned project files through Git;
do not copy `.env`, generated files, plans or local state.

## 1. Prepare the accounts

You need GitHub Actions, Redis Cloud administrative API credentials, and an AWS
account for S3 state and GitHub OIDC. The state account is independent of the
Redis Cloud hosting provider. Confirm billing, region/service availability,
network CIDRs and application access before deploying.

Local tools require Terraform 1.16.7+, Python 3.12+ and AWS CLI. For Python helpers:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 2. Bootstrap state storage

Run with AWS credentials authorized to create/configure the backend and IAM:

```bash
cd stacks/state-backend
cp terraform.tfvars.example terraform.tfvars
# Set the bucket, region and existing-role or new-role options.
terraform init
terraform plan
terraform apply
```

`create_bucket = true` creates and owns the bucket. Use `false` before the first
bootstrap for a bucket provisioned elsewhere; the stack still configures its
encryption, versioning, access policy and ownership controls. Keep this choice
stable. To adopt an existing bucket, keep it true and import into
`module.state_backend.aws_s3_bucket.this[0]` before applying. Earlier installations
that skipped bucket creation must select false or perform that explicit import.

Keep bootstrap state backed up outside Git. Use a private, encrypted, versioned
bucket with restricted access. Define retention for state and plan-bundle versions.
S3-managed encryption is the reference path; custom KMS requires the appropriate
key policy and role permissions to be configured separately.

## 3. Configure GitHub

Set repository variables from the bootstrap outputs:

| Variable | Purpose |
| --- | --- |
| `TF_STATE_BUCKET` | State and private reviewed-plan storage |
| `TF_STATE_REGION` | Bucket region |
| `AWS_GITHUB_ACTIONS_ROLE_ARN` | OIDC role with backend access |
| `REDISCLOUD_ENVIRONMENT` | Approval environment; defaults to `dev` |
| `REDISCLOUD_RUNNER` | Optional runner label; defaults to `ubuntu-latest` |

Create the selected GitHub environment with required reviewers and allowed
deployment branches. Its name must match the OIDC trust policy. For the bootstrap's
default `prod` role map, set `REDISCLOUD_ENVIRONMENT = prod`. Plan jobs also need
their branch subject trusted because they run outside an environment.

Set repository secrets `REDISCLOUD_ACCESS_KEY` and `REDISCLOUD_SECRET_KEY`.
Leave `REDISCLOUD_URL` unset for the public API; set it only for an intentional
alternative endpoint. The default uses the official Registry provider
2.20.0 and requires no Go build or provider checkout token. An optional private
source checkout may need `REDISCLOUD_PROVIDER_CHECKOUT_TOKEN`. Restrict workflow
and secret changes to trusted maintainers: deployment approval does not restrict
what workflow authors can do with repository credentials.

## 4. Prepare the configuration

Start with `configs/fetch-rewards/subscriptions/demo-ai-us-east-1.json`. For another
namespace, use `configs/<customer>/subscriptions/<file>.json`.

Replace demo billing, names, region, CIDR and source IPs. Include the Agent Memory
service egress addresses required for the selected region and any application
addresses needing direct database access. Confirm those addresses with the
service team; the example is not a production network policy.

For credit-card billing, supply `payment_method_id` or both `payment_card_type`
and `payment_card_last_four`. Use database names unique across the account's
managed subscriptions: their ACL names are account-scoped and derived from them.

Choose durable state/map keys once. `customer` and `environment` labels do not
select credentials, a backend or an approval environment. See the
[configuration reference](configuration-reference.md) for ownership and inputs.

## 5. Run the pipeline

Open **Redis Cloud Config Apply** from the approved branch.

| Input | Use |
| --- | --- |
| `config_path` | Versioned subscription JSON |
| `operation` | `plan` to preview; `apply` to review and deploy |
| `rediscloud_provider_source` | `registry` (default) for the locked official release; `branch` for development |
| `rediscloud_provider_ref` | Source commit/ref used in branch mode |

Keep `registry` selected across plan, apply and destroy. All Redis Cloud stacks
pin provider 2.20.0, including checksums for Linux Actions runners and macOS.
The official provider includes its SDK; no separate SDK installation is needed.
Switching provider builds alone preserves resource identity. This single-state
layout additionally requires [migration](state-migration.md) for existing
multi-state deployments. Review a plan before applying. Follow [maintenance](maintenance.md) for upgrades.

Read the complete Terraform plan before approval. Subscription, database and
Agent Memory changes are planned together in one state. One approval applies
that exact saved plan; it expires one hour after planning. Unchanged runs request
no approval. Failure stops execution without rolling back completed changes.

Follow the [walkthrough](demo-guide.md) for add/update/remove/teardown. Config
Destroy requires confirmation and can target one store with `agent_memory_key`.
External resources and the backend remain outside that teardown.

## 6. Connect applications

Agree delivery of store IDs, endpoints and runtime keys before deployment.
Generated runtime keys are sensitive outputs in the deployment state. `secret_ref`
records a desired destination; no automatic Secrets Manager publication is
implemented. Do not expose keys through Actions summaries or public artifacts.

The example uses platform-managed models and needs no model-provider key. BYO
models require both `llm` and `embedding`, with GitHub secrets
`AGENT_MEMORY_LLM_API_KEY` and `AGENT_MEMORY_EMBEDDING_API_KEY`. Reference their
environment-variable names in JSON. Update the secret and increment its
`api_key_version` when rotating. See the configuration reference for details.
