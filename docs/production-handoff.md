# Handoff and recovery

The customer owns its repository, Redis Cloud account, backend and operating
procedures. PS can maintain a separate reference template; customer deployments
do not depend on PS operating this repository on their behalf.

## Scope and release baseline

This reference manages a Pro single-region subscription, databases and ACLs,
Agent Memory stores and their runtime keys. The qualified cloud path is AWS.
Active-Active, CMEK, private connectivity and additional Iris services need
separate configuration contracts and lifecycle qualification.

The workflow baseline is Terraform 1.16.7 and an immutable provider revision.
Agent Memory currently uses a source build. Before handing off an official
release, select the released provider version containing the reviewed feature,
update lock files and rehearse the upgrade. If a customer deliberately uses the
pinned source build, record that choice and retain access to its source and Go
dependencies. `registry` mode must not be selected before its locked version
actually includes Agent Memory.

## Configure the customer repository

1. Follow [customer setup](customer-setup.md) in the customer's accounts. Use a
   private, encrypted, versioned S3 bucket and least-privilege OIDC access.
2. Set `REDISCLOUD_ENVIRONMENT` to the production GitHub environment. Match its
   OIDC subject and configure reviewers and allowed deployment branches. The
   plan role also needs its branch subject. Restrict workflow and secret changes
   to trusted repository maintainers.
3. Review Redis Cloud account permissions, billing, region, CIDR, TLS, source IPs,
   persistence and backup requirements. Confirm application connectivity and the
   service's availability in the customer's account.
4. Copy the example, select durable state/map keys and review the JSON as a PR.
   Preview the configuration before its first deployment.
5. Agree how applications receive runtime keys and store IDs. Generated keys are
   sensitive state outputs; `secret_ref` does not deliver them automatically.
6. Define backend access, state-version retention and retention of encrypted plan
   bundles. Removing a current S3 object does not remove its previous versions.

Anyone allowed to change workflows using repository secrets can use those
credentials. Environment approval controls deployment; it does not replace
repository access control. Never paste secrets, plan JSON or state into PRs.

## Routine changes

Edit JSON, open a PR and review the diff. After merging, run Config Apply from the
approved branch. The summary lists actions, changed field names and replacements.
One approval authorizes the complete configuration, including explicitly deferred
plans. On a new deployment, dependent plans can only be generated after their
subscription/database exists. Review that distinction before approving.

The approved bundle binds configuration commit, run/attempt, Terraform version,
provider binary, stack locks, state bucket/region and approval environment. A
change to any checked binding requires a fresh plan. Approval expires one hour
after planning; unchanged configurations request no deployment approval.

To rotate a runtime key without immediately revoking the application's current
key, enable an additional named key, deploy, deliver it to the application and
confirm authentication. Then remove or disable the old key and deploy again.
Renaming an existing key can replace it; inspect the plan before using that path.

For model keys, update the GitHub secret and increment its `api_key_version` in
JSON. The model credential is write-only in provider state. Root input files and
encrypted plan bundles still contain sensitive values and require restricted
access and retention management.

## Failed or interrupted execution

Completed operations are not automatically rolled back. Preserve the JSON and
read the failed step before retrying. Generate a new plan from the same durable
keys: Terraform refreshes the existing states and proposes the remaining work.

- For API errors, resolve the reported service issue or invalid configuration and
  review a fresh plan. Do not repeatedly dispatch the same failing deployment.
- For a stale S3 lock, verify that no workflow or Terraform operation is active.
  Only an authorized operator may unlock the exact state after checking its lock
  ID; do not remove lock objects blindly.
- If an API create succeeded but Terraform did not save its identity, identify
  the exact resource and reconcile it by import before retrying. Do not create a
  second copy to conceal a state problem.
- If an omitted state's identity or shape is unfamiliar, the runner stops.
  Back up that state version and reconcile it explicitly. Early, unreleased
  provider builds used a different block shape; do not assume that changing the
  provider pin automatically migrates their state. Use the compatible build to
  tear down a disposable fixture or rehearse a backed-up import migration.
- A selective destroy leaves the JSON unchanged. Remove the corresponding entry
  too if the resource should not return on the next apply.

Before restoring an S3 state version, confirm resource identities against the
API and check that another apply has not progressed. Restoring state changes
Terraform's record; it does not restore infrastructure or application data.

## Store replacement and context

A replacement has a new store ID and runtime keys. The service does not migrate
application context into that new identity automatically. Plan application
references and any required data migration before accepting the replacement.

Loss of access through the old store ID is not proof of physical data erasure.
Deletion/retention semantics, backup restoration and compliance requirements need
the service's documented contract. This project does not add an implicit flush.

## Inventory, history and future maintenance

Git records desired configuration history; Actions retains execution records;
Terraform state records managed identities as of the latest refresh. These are
not a live account-wide inventory. Scheduled drift detection and adoption of
console-created resources are outside the current reference.

Keep the reference version and customer customizations recorded. Review provider
and template upgrades in a branch, run local regression/stack checks, then repeat
the isolated workflow lifecycle before promoting them. Use
[the configuration reference](configuration-reference.md) when adding fields and
[the architecture guide](config-driven-architecture.md) when changing execution.
