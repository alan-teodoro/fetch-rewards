# Execution and maintenance

For account setup and daily operations, use [the customer guide](customer-setup.md).
For a worked example, use [the walkthrough](demo-guide.md).

## Component responsibilities

| Component | Responsibility |
| --- | --- |
| `configs/<customer>/subscriptions/*.json` | Desired resources for one subscription |
| `stacks/subscription`, `stacks/database`, `stacks/agent-memory` | Terraform resource configuration and outputs |
| `scripts/rediscloud_config.py` | Validate JSON and render stack inputs plus a manifest |
| `scripts/rediscloud_inventory.py` | Find previously managed entries omitted from the configuration |
| `scripts/rediscloud_plan.py` | Determine whether a dependency is available for planning |
| `scripts/rediscloud_review.py` | Plan, freeze approved inputs and execute reviewed changes |
| `rediscloud-config.yml`, `rediscloud-destroy.yml` | Manual customer entry points |
| `rediscloud-phase.yml` | Shared review and approval jobs |
| `terraform-validate.yml` | Formatting, configuration tests and stack validation |
| `scripts/internal/`, `provider-validation.yml` | Opt-in provider engineering tests |

Resource behavior belongs in the Terraform stacks. Keep workflow YAML focused
on credentials and job execution. Keep configuration validation grouped by
resource in the renderer; preserve clear errors pointing to the JSON field.

## State identity and ownership

A configuration's `subscription_key` and database/store map keys determine its
state paths:

```text
subscriptions/<subscription_key>/subscription.tfstate
subscriptions/<subscription_key>/databases/<database_key>.tfstate
subscriptions/<subscription_key>/agent-memory/<store_key>.tfstate
```

Names are display attributes; map keys are durable identities. Renaming a key,
importing an existing resource or transferring ownership requires explicit state
reconciliation. The runner does not automatically import existing resources.

Removing a managed store or database from JSON discovers its existing state and
produces a deletion-only plan. Unknown state layouts, ambiguous identity and
ownership changes stop reconciliation. Deletions run before creates/updates,
with stores removed before their databases. Full destroy also includes omitted
managed entries. Selective destroy targets only the requested store.

## Review and execution

Apply orders subscription → databases → stores; destroy reverses that order.
Existing dependency chains are planned before approval. New, replaced or renamed
parents can defer downstream plans. The review links the exact configuration
and identifies these deferred steps before one approval authorizes the rollout.
Deferred inputs are frozen, and their plans are generated after dependencies
exist. Failure stops later work; completed changes are not rolled back.

The review bundle binds saved plans, frozen variables, lock files and the exact
development provider binary to checksums and commit/run/attempt metadata. Apply
checks those bindings and rejects stale bundles after one hour. Reviewed plans
are reused; only explicitly deferred plans are generated after approval.

Bundles are encrypted in S3 and excluded from GitHub artifacts. Generated
variables use owner-only permissions but can contain credentials. Write-only
provider attributes do not make these root inputs ephemeral. Removing the
current bundle after execution does not remove older S3 versions; configure
backend retention separately. Public review summaries omit secret values.

## Isolation and inventory limits

Customer apply/destroy jobs share one concurrency group, serializing operations
across configuration paths in this repository. State prefixes organize resources;
IAM policy controls access to the bucket.

The current workflows use one Redis Cloud credential pair, one backend setup and
the GitHub environment `dev`. JSON `customer` and `environment` fields are
metadata; they do not select another account, credential set or approval policy.
Use a separately configured repository for each customer under this template.

Git records desired configuration history. Actions records execution history
subject to its retention settings. Terraform state records managed resources as
of the last refresh; it is not a live inventory of the whole Redis Cloud account.
Scheduled drift detection and a consolidated inventory view are not implemented.

## Making changes

- For a new configuration field, update the renderer, stack inputs, example and
  relevant tests together. Preserve `schema_version` compatibility or provide a
  migration path.
- For lifecycle changes, run the regression suite and rehearse the affected path
  on isolated infrastructure. Preview alone does not exercise deferred applies.
- For a provider upgrade, update workflow defaults and stack locks as needed,
  validate the stacks and test the upgrade. Build mode is temporary until an
  official release contains Agent Memory; apply reuses the reviewed binary.
- Keep provider investigation and historical run evidence in
  [internal validation history](internal/demo-validation-history.md).

Future Active-Active, CMEK, connectivity and Iris services need explicit input
contracts and lifecycle coverage. Organize resource code by service; add
cloud-specific variants inside the relevant service when required. The AWS state
backend is independent of the Redis Cloud hosting provider.
