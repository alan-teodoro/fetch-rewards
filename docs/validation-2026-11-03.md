# Delivery validation — November 3, 2026

This records the reference template validation for the customer handoff in
[PR #4](https://github.com/alan-teodoro/fetch-rewards/pull/4).

## Tested baseline

- Terraform 1.16.7, verified against the official download checksum.
- Python 3.12 and the dependencies pinned in `requirements-dev.txt`.
- Redis Cloud provider source revision
  `6ac1f02d497616ccd3b80791f7032661a85a0429`, using the released Go SDK v0.53.0.
- The versioned Fetch JSON example and all historical configuration fixtures.

The template still builds this immutable provider revision. At validation time,
the Agent Memory provider PR was open and the latest published provider release
was v2.19.3. This evidence does not certify a later release automatically. Before
switching to Registry mode, select the official release containing Agent Memory,
update all relevant stack lock files and validate that exact upgrade.

## Results

| Check | Result |
| --- | --- |
| Complete Python regression suite with the current provider binary | 82 passed, no skipped tests |
| State bucket creation and unchanged reapply, with AWS mocked | 2 passed |
| Existing bucket reference and unchanged reapply, with AWS mocked | 2 passed |
| Terraform validation of all four stacks | Passed |
| Demo JSON rendered into an Agent Memory plan with the current provider | Passed; local synthetic database identity, no refresh or cloud backend |
| Workflow syntax (Actionlint) | Passed |
| Terraform formatting and Git whitespace checks | Passed |
| Ruff checks for the customer configuration/execution modules and entry points | Passed |
| Pattern scan of tracked files for common credential/private-key formats | No matches; not a full historical secret audit |

The regression suite covers dependency ordering, deferred plans, unchanged runs,
addition and omission of resources, selective/full destruction, ownership checks,
immutable changes, BYO credentials/state reconstruction, API failures, preserved
identities, bundle tampering/expiry and approval/backend bindings. Terraform
contract tests use the actual provider binary with synthetic state or local HTTP
simulators. They do not create customer infrastructure.

## Issues corrected before merge

Bucket ownership previously depended on whether the bucket currently existed.
After the first bootstrap, that condition could remove the managed bucket from
configuration and propose its deletion. Ownership is now explicit through
`create_bucket`; both owned and pre-existing bucket paths have repeatability
tests. Existing installations must preserve their ownership choice or explicitly
import/migrate their bucket, as described in the setup guide.

Internal fault checks expected an acknowledged create with a failed follow-up
read to succeed. The current provider reports the readiness error and preserves
the acknowledged ID. Tests now verify that failure, the saved identity and a
replacement proposal without automatically applying that replacement or creating
a dependent key. Fixture teardown remains explicit and ownership-scoped.

The workflow provider pin was updated to the current reviewed candidate. The
setup/recovery guides also describe account-scoped ACL names and unsuccessful
creation recovery.

## Cloud and handoff boundaries

No Redis Cloud or AWS resources were created, changed or destroyed during this
validation. Earlier isolated QA lifecycle rehearsals are documented in the PR and
the handoff guide; those used the provider available at the time. The customer's
accounts, networking and credentials have not been validated by these local tests.

Before the customer's first deployment:

1. Use the delivery branch/commit whose PR checks passed; do not copy generated
   local files, `.env`, state or plans into the customer's repository.
2. Configure the customer's Redis Cloud credentials, AWS backend/OIDC role and
   approval environment. Match branch and environment subjects explicitly.
3. Replace demo billing, CIDR, region and source-IP settings. Keep durable state
   keys and use database names unique within the account's managed subscriptions.
4. Agree how applications receive store IDs and runtime keys. `secret_ref` remains
   metadata and does not publish to a secret manager.
5. Run a reviewed preview, then rehearse create, unchanged apply, update and
   teardown on isolated resources in the target account before wider adoption.

The qualified reference path is AWS, Pro single-region, S3-managed state
encryption and the documented approval flow. Other connectivity, encryption and
service combinations need their own qualification. See
[handoff and recovery](production-handoff.md) for operating limits and recovery.
