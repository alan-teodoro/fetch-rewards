# Maintenance and recovery

## Execution path

1. Validate the versioned JSON and render one private tfvars file and a manifest.
2. Initialize `stacks/deployment` with the backend key from `subscription_key`.
3. Generate one complete Terraform plan and a non-sensitive review summary.
4. After environment approval, verify and apply that exact saved plan.

There are no deferred plans. Terraform references connect the subscription ID to
the databases and each database ID to its Agent Memory stores. Terraform manages
ordering, omitted resources and partial-apply state itself.

## Code map

| File or directory | Responsibility |
| --- | --- |
| `stacks/deployment/main.tf` | Compose managed modules and resolve external parents |
| `stacks/deployment/variables.tf` | Typed input tree; secrets are separate from instance keys |
| `stacks/deployment/backend.tf` | S3 state backend and locking |
| `stacks/subscription`, `stacks/database`, `stacks/agent-memory` | Resource-specific modules; also usable as standalone roots |
| `scripts/rediscloud_config.py` | JSON validation and rendering CLI |
| `scripts/rediscloud/config.py`, `subscription.py`, `database.py`, `agent_memory.py` | Input normalization, references and model credentials |
| `scripts/rediscloud/lifecycle.py` | One plan/apply; additional checks over Terraform's documented JSON plan |
| `scripts/rediscloud/bundles.py` | Encrypted saved-plan storage, integrity and approval bindings |
| `scripts/rediscloud/terraform.py` | Terraform CLI calls and dependency-lock verification |
| `scripts/rediscloud/reporting.py` | Summaries with secret values omitted |
| `scripts/rediscloud/stacks.py` | Stable backend key and public summary fields |

No delivery script lists state objects, downloads state files or interprets their
internal JSON. AWS CLI access in the review code is exclusively for encrypted
plan bundles. Terraform alone reads and writes state through its S3 backend.

## State and identity

Each JSON uses one state. Use a unique `subscription_key` for each independent
deployment in the same backend; two files sharing that key manage the same state:

```text
subscriptions/<subscription_key>/terraform.tfstate
```

Module addresses are stable map-key identities:

```text
module.subscription[0]
module.database["shared_agent_memory"]
module.agent_memory["shopping_agent"]
```

Removing a managed entry from JSON makes Terraform propose deleting its module's
resources. A removed database key still referenced by an agent fails input
validation. Plan checks also reject retained agents using a deleted database's
raw ID, and managed-to-external changes that would silently delete owned resources.
These checks cover this deployment, not every consumer in the account.

Ownership transfers, renaming keys and adopting existing resources require an
explicit maintenance procedure. Existing multi-state installations must follow
[state migration](state-migration.md) before changing workflows/backend keys.

## Approval and concurrency

One approval covers one saved plan. Its bundle binds the commit, run/attempt,
Terraform version, backend, environment, provider identity and dependency lock.
It expires after one hour. Apply validates the complete bundle before using it;
it never silently replans after approval. A stale plan must be regenerated.

Apply and destroy share a GitHub concurrency group. Terraform's S3 lock protects
the single state. Failure does not roll back successful cloud operations;
Terraform records completed resources so the next plan can reconcile them.

Selective destroy uses a normal plan with the selected store omitted from the
rendered inputs, leaving parents and other stores configured. The plan must only
delete resources in that store's module; unrelated changes stop the operation.
The JSON is unchanged, so a subsequent ordinary apply recreates that store unless
its entry is also removed. Full destroy uses Terraform's native destroy plan.

## Local use

With AWS backend access and Redis Cloud credentials set in the environment:

```bash
python3 scripts/rediscloud_config.py render \
  --config configs/fetch-rewards/subscriptions/demo-ai-us-east-1.json \
  --out-dir .generated/demo
terraform -chdir=stacks/deployment init \
  -backend-config="bucket=<private-state-bucket>" \
  -backend-config="region=us-east-1" \
  -backend-config="key=subscriptions/demo-ai-us-east-1/terraform.tfstate"
terraform -chdir=stacks/deployment plan \
  -var-file=../../.generated/demo/deployment.auto.tfvars.json -out=tfplan
# Review the full plan before executing it.
terraform -chdir=stacks/deployment apply tfplan
```

Use the same backend and key as the workflow for the same infrastructure. For a
new isolated test, use distinct resource names and a distinct subscription key.
Do not point an unmigrated deployment at an empty new state.

## Credentials

State, tfvars and saved plans can contain passwords/API keys. Keep them private,
encrypted and out of Git/logs. Sensitive Terraform outputs suppress display;
they do not encrypt state. Runtime API keys are generated once and stored in
state. `secret_ref` is metadata; automatic Secrets Manager publication is not
implemented. BYO models require both model identities and their environment keys;
increment `api_key_version` when rotating a model credential.

## Verification

Before changing the automation or provider version, run:

```bash
python3 -m unittest discover -s tests -v
TEST_REGISTRY_PROVIDER=1 python3 -m unittest discover -s tests -p test_terraform_contract.py -v
terraform fmt -check -recursive
terraform -chdir=stacks/deployment init -backend=false
terraform -chdir=stacks/deployment validate
```

The offline contract uses fake credentials and synthetic state. It verifies
unknown managed-parent IDs, native deletion and write-only model credentials
without creating cloud resources. Rehearse creation, unchanged apply, updates,
addition, selective deletion and full teardown on isolated infrastructure before
adopting lifecycle changes.

For existing infrastructure, rehearse the state migration separately and require
a refreshed plan with no cloud resource creation, replacement, update or deletion.
