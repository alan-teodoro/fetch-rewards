#!/usr/bin/env python3
"""Observe service-owned limits and verify rejection atomicity on disposable fixtures."""

import copy
import os

from provider_live_faults import FixtureProxy
from provider_live_validation import Api, ApiError, Fixture, KEY, Results, STORE, configuration_snapshot, custom_type


def contract_case(api, database, binary, mode):
    fixture = Fixture(database, binary, api)
    try:
        if mode == "oversized-create-prompt":
            spec = custom_type("qa_prompt")
            spec["extraction_strategy"]["prompt"] = "x" * 10001
            fixture.config["custom_memory_types"] = [spec]
            fixture.write()
            fixture.plan({STORE: ["create"], KEY: ["create"]})
            response = fixture.command("apply", "-input=false", "-no-color", "checked.tfplan", allowed=(0, 1))
            owned = [s for s in api.stores(database) if s.get("name") == fixture.name]
            if response.returncode:
                assert not owned, "Rejected create left a remote store outside Terraform ownership"
            return {"accepted_by_current_service": response.returncode == 0,
                    "remote_store_count_after_response": len(owned), "former_prompt_limit": 10000}

        if mode in ("unknown-built-in-id", "unknown-matcher-kind"):
            fixture.apply({STORE: ["create"], KEY: ["create"]})
            before = configuration_snapshot(fixture.remote())
            identity = fixture.identities()
            policy = {"enabled": True}
            if mode == "unknown-built-in-id":
                policy["builtInDetectors"] = {"enabled": True, "detectors": [{"id": "not_a_builtin_detector", "enabled": True, "action": "redact"}]}
            else:
                policy["customDetectors"] = {"enabled": True, "detectors": [{"name": "bad_kind", "enabled": True, "action": "redact", "matcher": {"kind": "not_a_matcher", "regex": {"pattern": "TICKET-[0-9]+"}}}]}
            fixture.intent_names.add(fixture.name + "-catalogue")
            fixture.write()
            try:
                api.wait(api.request("/memory-stores/" + identity[0], "PATCH", {"name": fixture.name + "-catalogue", "longTermMemoryExclusions": policy}))
                rejected, status, catalogue = False, None, []
            except ApiError as error:
                rejected, status = True, error.status
                text = str(error.payload).lower()
                catalogue = [name for name in ("credit-card", "email", "ip-address", "phone", "us-ssn") if name in text]
            after = configuration_snapshot(fixture.remote())
            if rejected:
                assert before == after, "Rejected catalogue update partially mutated remote configuration"
            assert fixture.identities() == identity, "Catalogue probe changed identity or secret"
            fixture.intent_names.add(fixture.name + "-catalogue")
            return {"api_rejected": rejected, "status": status, "remote_unchanged": before == after, "known_ids_advertised_in_error": catalogue}

        fixture.config["custom_memory_types"] = [custom_type("qa_one"), custom_type("qa_two"), custom_type("qa_three")]
        fixture.write()
        fixture.apply({STORE: ["create"], KEY: ["create"]})
        identity = fixture.identities()
        before = configuration_snapshot(fixture.remote())
        candidate = copy.deepcopy(fixture.config)
        if mode == "cumulative-custom-type-quota":
            candidate["custom_memory_types"].append(custom_type("qa_four"))
        else:
            candidate["custom_memory_types"][0]["extraction_strategy"]["prompt"] = "x" * 10001
        candidate["name"] = fixture.name + "-probe"
        fixture.write(candidate)
        with FixtureProxy(api, fixture, "observe") as proxy:
            proxy.owned_ids.add(identity[0])
            fixture.plan({STORE: ["update"]})
            response = fixture.command("apply", "-input=false", "-no-color", "checked.tfplan", allowed=(0, 1))
            diagnostic = " ".join((response.stdout + response.stderr).split())
            preserved_details = all(" ".join(info.split()) in diagnostic for info in proxy.async_details)
            extra = {"async_additional_info_observed": bool(proxy.async_details),
                     "provider_preserved_async_additional_info": preserved_details if proxy.async_details else None}
        fixture.environment["REDISCLOUD_URL"] = api.base
        after = configuration_snapshot(fixture.remote())
        if response.returncode:
            assert after == before, "Rejected compound update partially changed the store"
        assert fixture.identities() == identity, "Contract probe changed identity or runtime secret"
        assert preserved_details, "Provider omitted additionalInfo returned by the actual task"
        return {"accepted_by_current_service": response.returncode == 0,
                "remote_unchanged": before == after, "identity_preserved": True,
                "custom_type_count_after_response": len(after.get("customMemoryTypes") or []), **extra}
    finally:
        fixture.environment["REDISCLOUD_URL"] = api.base
        errors = fixture.cleanup()
        assert not errors, "Contract fixture cleanup needed API fallback reconciliation"


def main():
    assert os.environ.get("LIVE_VALIDATION_CONFIRM") == "isolated-qa-only", "Explicit isolated-QA opt-in is required"
    results = Results(os.environ["LIVE_VALIDATION_REPORT"])
    api = Api()
    for mode in ("cumulative-custom-type-quota", "oversized-create-prompt", "oversized-update-prompt", "unknown-built-in-id", "unknown-matcher-kind"):
        results.case(mode, lambda m=mode: contract_case(api, os.environ["AGENT_MEMORY_TEST_DATABASE_ID"], os.environ["CANDIDATE_PROVIDER_BINARY"], m))
    results.data["cleanup_verified"] = not any(c["status"] == "failed" for c in results.data["cases"])
    results.save()
    assert results.data["cleanup_verified"], "Service contract checks failed; inspect assertion report"


if __name__ == "__main__":
    main()
