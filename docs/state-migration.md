# Migration from separate states

**Do not change the backend key for existing infrastructure before migrating its
state.** Rehearse this procedure with backups before applying it to a deployment.

Retain every existing subscription, database, store ID, generated runtime key and
ACL password. This changes Terraform ownership addresses; it does not recreate
cloud resources.

## Address mapping

| Existing state | Destination in the unified state |
| --- | --- |
| `subscriptions/<subscription_key>/subscription.tfstate` | Prefix each existing root address with `module.subscription[0].` |
| `subscriptions/<subscription_key>/databases/<database_key>.tfstate` | Prefix with `module.database["<database_key>"].` |
| `subscriptions/<subscription_key>/agent-memory/<store_key>.tfstate` | Prefix with `module.agent_memory["<store_key>"].` |

The destination backend key is
`subscriptions/<subscription_key>/terraform.tfstate`. Resource types/names inside
the leaf modules remain the same. Data-source entries may be moved too; they do
not own cloud resources. Preserve resource instances, private provider metadata,
passwords and generated keys rather than re-importing resources and losing secrets.

## Controlled migration procedure

1. Pause infrastructure workflows and other writers. Confirm AWS/Redis account,
   configuration commit, Terraform/provider versions and the exact three source
   backend keys. Keep the repository's normal approval protections enabled.
2. Use Terraform's official `state pull` interface to obtain private backups from
   each configured legacy backend in isolated working directories. Do not parse
   or edit raw state JSON, print it, or publish it as a GitHub artifact.
3. Enumerate addresses with `terraform state list`. Rehearse the mapping using
   `terraform state mv` with isolated local state files and the destination
   module addresses above. This must preserve every managed identity and secret.
4. Verify the consolidated result with Terraform's inspection commands. Compare
   original resource IDs and named API-key identity; do not display key values.
5. Prepare and review the cutover/rollback steps for backend ownership. Only then
   use Terraform's official state interfaces to publish the consolidated state.
   Retire old active states so two configurations cannot manage the same resource.
   Keep versioned/private rollback backups and prohibit legacy workflow execution.
6. Initialize the new root with the new key, then produce a normal refreshed plan
   against production. Require **zero cloud resource creates, updates, replacements
   or deletions**. Root output changes alone may need an approved state-only apply.
   Any cloud change stops the cutover for investigation.
7. After approval and a successful unchanged plan, release the new workflow and
   restore normal operation. Verify application references and store/key IDs.

This document is a preparation checklist, not a tested migration command script.
The exact state-move/publish sequence must first be rehearsed offline, including
rollback and failure between source and destination writes. Do not overwrite the
existing state or infer resource identity from names alone.
