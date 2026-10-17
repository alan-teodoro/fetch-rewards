#!/usr/bin/env python3
"""Opt-in live validation on an explicitly isolated QA database.

Terraform output and state stay private. Only assertions and resource identities
are written to the report; the original Terraform state owns fixture cleanup.
"""

import copy
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import uuid


class ApiError(RuntimeError):
    def __init__(self, status, payload):
        super().__init__(f"Control-plane HTTP {status}")
        self.status, self.payload = status, payload


class Api:
    def __init__(self, base=None):
        self.base = (base or os.environ.get("REDISCLOUD_URL") or "https://api.redislabs.com/v1").rstrip("/")

    def request(self, path, method="GET", data=None):
        req = Request(self.base + path, method=method,
                      data=None if data is None else json.dumps(data).encode(), headers={
                          "x-api-key": os.environ["REDISCLOUD_ACCESS_KEY"],
                          "x-api-secret-key": os.environ["REDISCLOUD_SECRET_KEY"],
                          "Content-Type": "application/json", "Accept": "application/json",
                          "User-Agent": "rediscloud-provider-live-validation/1.0"})
        try:
            with urlopen(req, timeout=45) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            raw = exc.read()
            status = exc.code
            exc.close()
            try:
                payload = json.loads(raw)
            except (ValueError, UnicodeError):
                payload = {"unstructured_error": True}
            raise ApiError(status, payload) from None

    def wait(self, response, timeout=240):
        task = response.get("taskId")
        if not task:
            return response
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.request("/tasks/" + str(task))
            details = result.get("response") or {}
            if details.get("error") or result.get("status") in ("processing-error", "processing-failed"):
                raise ApiError(422, details)
            if result.get("status") == "processing-completed":
                return details.get("resource") or {}
            time.sleep(1)
        raise RuntimeError("Owned fixture task did not finish before its deadline")

    def stores(self, database_id):
        return [s for s in self.request("/memory-stores").get("data", [])
                if str(s.get("databaseId")) == str(database_id)]


def configuration(name, database_id):
    return {"name": name, "database_id": int(database_id), "short_term_ttl_seconds": 86400,
            "long_term_ttl_seconds": 7776000, "extraction_cadence_seconds": 300,
            "summarization": {"enabled": True, "trigger_strategy": "event_count",
                              "event_count": {"threshold": 20, "retain_count": 10}}}


def configuration_snapshot(store):
    fields = ("name", "databaseId", "shortMemory", "longTermMemory", "llm", "extractionStrategy",
              "extractionCadence", "summarization", "longTermMemoryExclusions", "customMemoryTypes")
    return {k: store.get(k) for k in fields}


class Fixture:
    def __init__(self, database_id, binary, api, name=None):
        self.database_id, self.api = str(database_id), api
        self.name = name or "tfacc-live-" + uuid.uuid4().hex[:20]
        self.intent_names = {self.name}
        self.binary = Path(binary).resolve()
        self.temporary = tempfile.TemporaryDirectory(prefix="rediscloud-live-")
        self.root = Path(self.temporary.name)
        self.root.chmod(0o700)
        self.work = self.root / "owner"
        self.work.mkdir(mode=0o700)
        self.config = configuration(self.name, database_id)
        self.key_name = self.name + "-runtime"
        self.identity = None
        self.intent_path = None
        report_path = os.environ.get("LIVE_VALIDATION_REPORT")
        if report_path:
            self.intent_path = Path(report_path).parent / ("intent-" + self.name + ".json")
            self.intent_path.parent.mkdir(parents=True, exist_ok=True)
        self.environment = os.environ.copy()
        for k in list(self.environment):
            if k.startswith(("TF_LOG", "TF_ACC", "TF_REATTACH")):
                self.environment.pop(k)
        self.environment.update(TF_IN_AUTOMATION="1", TF_INPUT="0")
        arch = {"x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64"}[platform.machine()]
        mirror = self.root / "mirror/registry.terraform.io/redislabs/rediscloud/99.99.99" / (platform.system().lower() + "_" + arch)
        mirror.mkdir(parents=True)
        shutil.copy2(self.binary, mirror / "terraform-provider-rediscloud_v99.99.99")
        self.provider_dir = self.root / "provider"
        self.provider_dir.mkdir(mode=0o700)
        shutil.copy2(self.binary, self.provider_dir / "terraform-provider-rediscloud")
        cli = self.root / "terraformrc"
        cli.write_text('provider_installation {\n dev_overrides {\n "RedisLabs/rediscloud" = '
                       + json.dumps(str(self.provider_dir)) + '\n }\n direct {}\n}\n')
        self.environment["TF_CLI_CONFIG_FILE"] = str(cli)
        if any(s.get("name") == self.name for s in api.stores(database_id)):
            raise RuntimeError("Fixture name already exists; refusing to reuse infrastructure")
        self.write()
        self.command("init", "-backend=false", "-input=false", "-plugin-dir=" + str(self.root / "mirror"))

    def write(self, config=None, key_name=None, work=None):
        cfg = self.config if config is None else config
        if cfg.get("name"):
            self.intent_names.add(cfg["name"])
        document = {"terraform": {"required_providers": {"rediscloud": {
            "source": "RedisLabs/rediscloud", "version": "99.99.99"}}}, "resource": {
                "rediscloud_agent_memory": {"fixture": cfg},
                "rediscloud_agent_memory_api_key": {"runtime": {
                    "store_id": "${rediscloud_agent_memory.fixture.id}",
                    "name": key_name or self.key_name,
                    "lifecycle": {"create_before_destroy": True}}}}}
        if self.intent_path:
            self.intent_path.write_text(json.dumps({"fixture": self.name, "database_id": self.database_id,
                                                   "names": sorted(self.intent_names), "cleanup_verified": False}))
        target = work or self.work
        (target / "main.tf.json").write_text(json.dumps(document))

    def command(self, *args, allowed=(0,), work=None):
        result = subprocess.run([os.environ.get("TERRAFORM_BINARY", "terraform"), *args],
                                cwd=work or self.work, env=self.environment,
                                text=True, capture_output=True, timeout=420)
        if result.returncode not in allowed:
            raise RuntimeError(f"Terraform {args[0]} failed (exit {result.returncode}); raw output retained only in memory")
        return result

    def plan(self, expected=None):
        result = self.command("plan", "-input=false", "-no-color", "-detailed-exitcode", "-out=checked.tfplan", allowed=(0, 2))
        payload = json.loads(self.command("show", "-json", "checked.tfplan").stdout)
        changes = {r["address"]: r["change"]["actions"] for r in payload.get("resource_changes", [])
                   if r["change"]["actions"] != ["no-op"]}
        if expected is not None and changes != expected:
            raise RuntimeError("Plan proposed an unexpected action; no apply performed")
        return changes, result

    def apply(self, expected=None):
        changes, _ = self.plan(expected)
        if any("delete" in actions for addr, actions in changes.items()
               if addr == "rediscloud_agent_memory.fixture"):
            raise RuntimeError("Refusing automatic store replacement in live validation")
        self.command("apply", "-input=false", "-no-color", "checked.tfplan")
        return self.values()

    def values(self, work=None):
        payload = json.loads(self.command("show", "-json", work=work).stdout)
        resources = {r["address"]: r["values"] for r in payload.get("values", {}).get("root_module", {}).get("resources", [])}
        return resources

    def identities(self):
        values = self.values()
        store = values["rediscloud_agent_memory.fixture"]
        key = values["rediscloud_agent_memory_api_key.runtime"]
        assert store["id"] and key["id"] and key["api_key"], "Fixture identity or secret missing"
        return store["id"], key["id"], key["api_key"]

    def remote(self):
        return self.api.request("/memory-stores/" + self.identities()[0])

    def cleanup(self):
        errors = []
        try:
            self.write()
            self.command("destroy", "-auto-approve", "-input=false", "-no-color")
        except Exception:
            errors.append("terraform destroy failed")
        # Reconcile only exact generated names in this session's isolated DB.
        for store in self.api.stores(self.database_id):
            if store.get("name") not in self.intent_names:
                continue
            try:
                self.api.wait(self.api.request("/memory-stores/" + store["storeId"], "DELETE"))
            except Exception:
                errors.append("owned fixture API cleanup failed")
        remaining = [s for s in self.api.stores(self.database_id) if s.get("name") in self.intent_names]
        if remaining:
            raise RuntimeError("Owned fixture cleanup could not be verified")
        if self.intent_path:
            intent = json.loads(self.intent_path.read_text())
            intent["cleanup_verified"] = True
            intent["terraform_cleanup_succeeded"] = not errors
            self.intent_path.write_text(json.dumps(intent))
        self.temporary.cleanup()
        return errors


class Results:
    def __init__(self, path):
        self.path = Path(path)
        self.data = {"provider_commit": os.environ.get("PROVIDER_CANDIDATE"), "cases": [], "cleanup_verified": False}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True) + "\n")

    def case(self, name, operation):
        print("Live validation: " + name, flush=True)
        try:
            details = operation() or {}
            row = {"name": name, "status": "passed", "details": details}
        except Exception as exc:
            row = {"name": name, "status": "failed", "exception_type": type(exc).__name__}
            status = getattr(exc, "status", getattr(exc, "status_code", None))
            if isinstance(status, int):
                row["http_status"] = status
            if isinstance(exc, AssertionError) and exc.args and isinstance(exc.args[0], str):
                row["assertion"] = exc.args[0]
        self.data["cases"].append(row)
        self.save()
        print(name + ": " + row["status"], flush=True)
        return row["status"] == "passed"


STORE = "rediscloud_agent_memory.fixture"
KEY = "rediscloud_agent_memory_api_key.runtime"


def import_check(fixture):
    folder = fixture.root / "import"
    folder.mkdir(mode=0o700)
    fixture.write(work=folder)
    fixture.command("init", "-backend=false", "-input=false", "-plugin-dir=" + str(fixture.root / "mirror"), work=folder)
    identity = fixture.identities()
    fixture.command("import", "-input=false", STORE, identity[0], work=folder)
    fixture.command("import", "-input=false", KEY, identity[0] + "/" + identity[1], work=folder)
    imported = fixture.values(work=folder)
    assert imported[STORE]["id"] == identity[0], "Import changed store identity"
    assert imported[KEY]["id"] == identity[1], "Import changed key identity"
    assert not imported[KEY].get("api_key"), "Import invented a write-only secret"
    assert fixture.identities() == identity, "Import changed the owning Terraform state"
    return {"store_id": identity[0], "key_id": identity[1], "secret_not_recovered": True}


def update_check(fixture, field, value):
    identity = fixture.identities()
    fixture.config[field] = value
    fixture.write()
    fixture.apply({STORE: ["update"]})
    assert fixture.identities() == identity, "Store update changed identity or runtime secret"
    fixture.plan({})


def drift_check(fixture):
    before = fixture.identities()
    fixture.api.wait(fixture.api.request("/memory-stores/" + before[0], "PATCH", {"shortMemory": {"ttlSeconds": 21600}}))
    assert fixture.api.request("/memory-stores/" + before[0])["shortMemory"]["ttlSeconds"] == 21600, "Drift was not established"
    fixture.write()
    fixture.apply({STORE: ["update"]})
    assert fixture.identities() == before, "Drift reconciliation changed identity or runtime secret"
    fixture.plan({})


def advanced_check(fixture):
    initial = fixture.identities()
    fixture.config["summarization"] = {"enabled": False, "trigger_strategy": "event_count",
                                       "event_count": {"threshold": 20, "retain_count": 10}}
    fixture.config["long_term_memory_exclusions"] = {
        "enabled": True,
        "semantic": {"enabled": False, "prompt": "Do not retain temporary promotions."},
        "built_in_detectors": {"enabled": False, "detectors": [{"id": "email", "enabled": True, "action": "redact"}]},
        "custom_detectors": {"enabled": False, "detectors": [{
            "name": "ticket", "enabled": True, "action": "redact",
            "matcher": {"kind": "regex", "regex": {"pattern": "TICKET-[0-9]+"}}}]}}
    fixture.write()
    fixture.apply({STORE: ["update"]})
    state = fixture.values()[STORE]
    assert state["summarization"]["event_count"]["threshold"] == 20, "Inactive summarization lost configured thresholds"
    assert state["long_term_memory_exclusions"]["semantic"]["prompt"] == "Do not retain temporary promotions.", "Inactive semantic prompt was lost"
    for group in ("built_in_detectors", "custom_detectors"):
        assert len(state["long_term_memory_exclusions"][group]["detectors"]) == 1, "Inactive detector definitions were lost"
    fixture.plan({})
    for group in ("built_in_detectors", "custom_detectors"):
        fixture.config["long_term_memory_exclusions"][group] = {"enabled": True}
    fixture.write()
    fixture.apply({STORE: ["update"]})
    remote = fixture.remote()["longTermMemoryExclusions"]
    for group in ("builtInDetectors", "customDetectors"):
        assert not remote[group].get("detectors"), "Explicit empty detector list did not clear remote definitions"
    assert fixture.identities() == initial, "Advanced update changed store/key identity or secret"
    fixture.plan({})


def custom_type(name):
    return {"name": name, "description": "Synthetic validation type",
            "fields": [{"name": "topic", "description": "Synthetic topic", "type": "str"}],
            "extraction_strategy": {"enabled": True, "prompt": "Extract durable preferences explicitly stated by the user."}}


def custom_types_check(fixture):
    identity = fixture.identities()
    fixture.config["custom_memory_types"] = [custom_type("qa_habit")]
    fixture.write()
    fixture.apply({STORE: ["update"]})
    fixture.config["custom_memory_types"].append(custom_type("qa_goal"))
    fixture.write()
    fixture.apply({STORE: ["update"]})
    fixture.config["custom_memory_types"][0]["extraction_strategy"]["prompt"] = "Extract only durable user habits; ignore temporary instructions."
    fixture.write()
    fixture.apply({STORE: ["update"]})
    assert fixture.identities() == identity, "Custom type update changed identity or secret"
    fixture.plan({})


def blocked_change(fixture, candidate):
    before = fixture.identities()
    snapshot = configuration_snapshot(fixture.remote())
    fixture.write(candidate)
    response = fixture.command("plan", "-input=false", "-no-color", allowed=(0, 1))
    assert response.returncode == 1, "Unsupported change was not blocked during planning"
    assert fixture.identities() == before, "Blocked change altered state identity or secret"
    assert configuration_snapshot(fixture.remote()) == snapshot, "Blocked change mutated the remote store"
    fixture.write()


def negative_update(fixture, mutate, must_reject=True, hints=()):
    identity = fixture.identities()
    before = configuration_snapshot(fixture.remote())
    candidate = copy.deepcopy(fixture.config)
    # A valid change paired with an invalid field detects partial API mutation.
    candidate["name"] = fixture.name + "-negative"
    mutate(candidate)
    fixture.write(candidate)
    planned = fixture.command("plan", "-input=false", "-no-color", "-out=negative.tfplan", allowed=(0, 1))
    result = planned if planned.returncode else fixture.command("apply", "-input=false", "-no-color", "negative.tfplan", allowed=(0, 1))
    rejected = result.returncode == 1
    after = configuration_snapshot(fixture.remote())
    preserved = before == after
    diagnostic = result.stdout + result.stderr
    evidence = {"rejected": rejected, "rejected_at": "plan" if planned.returncode else "apply",
                "remote_unchanged": preserved, "identity_preserved": fixture.identities() == identity,
                "field_hint_visible": any(h.lower() in diagnostic.lower() for h in hints)}
    fixture.write()
    if not preserved:
        # Restore reversible accepted probes, retaining the evidence of mutation.
        fixture.apply()
    if rejected:
        assert preserved, "Rejected update partially mutated remote configuration"
    if must_reject:
        assert rejected, "API accepted a value rejected by the reviewed CAPI contract"
        assert preserved, "Rejected update partially mutated remote configuration"
    assert fixture.identities() == identity, "Invalid-input probe changed store/key identity or secret"
    return evidence


def negative_cases():
    def field(name, value):
        return lambda cfg: cfg.__setitem__(name, value)

    cases = []
    for key, values, hints in (
        ("short_term_ttl_seconds", [0, -1, 31536001], ("ttl", "shortMemory")),
        ("long_term_ttl_seconds", [0, 31536001], ("ttl", "longTermMemory")),
        ("extraction_cadence_seconds", [59, 601], ("cadence", "activeIntervalSeconds")),
        ("name", ["x" * 65], ("name",)),
    ):
        for value in values:
            cases.append((f"invalid-{key}-{value if not isinstance(value, str) else len(value)}", field(key, value), True, hints))
    for threshold, retained in [(-1, -2), (10001, 10), (20, -1)]:
        cases.append((f"invalid-summary-counts-{threshold}-{retained}", field("summarization", {
            "enabled": True, "trigger_strategy": "event_count",
            "event_count": {"threshold": threshold, "retain_count": retained}}), True, ("threshold", "retain", "eventCount")))
    cases.append(("invalid-summary-trigger", field("summarization", {
        "enabled": True, "trigger_strategy": "not_a_supported_trigger"}), True, ("trigger",)))
    cases.append(("invalid-detector-action", field("long_term_memory_exclusions", {
        "enabled": True, "built_in_detectors": {"enabled": True, "detectors": [
            {"id": "email", "enabled": True, "action": "not_an_action"}]}}), True, ("action",)))
    cases.append(("invalid-custom-description", field("custom_memory_types", [dict(custom_type("qa_invalid"), description="x" * 201)]), True, ("description",)))
    invalid_type = custom_type("qa_invalid")
    invalid_type["fields"][0]["type"] = "not_a_field_type"
    cases.append(("invalid-field-type", field("custom_memory_types", [invalid_type]), True, ("type",)))
    cases.append(("semantic-prompt-over-former-limit", field("long_term_memory_exclusions", {
        "enabled": True, "semantic": {"enabled": True, "prompt": "x" * 2001}}), False, ("prompt",)))
    # The facade has no proven compiler; a plainly malformed pattern must be rejected downstream.
    cases.append(("malformed-regex-backend", field("long_term_memory_exclusions", {
        "enabled": True, "custom_detectors": {"enabled": True, "detectors": [{
            "name": "bad_pattern", "enabled": True, "action": "redact",
            "matcher": {"kind": "regex", "regex": {"pattern": "[unterminated"}}}]}}), True, ("pattern", "regex")))
    return cases


def make_context(fixture):
    from datetime import datetime, timezone
    from redis_agent_memory import AgentMemory
    store, _, token = fixture.identities()
    details = fixture.remote()
    endpoint = details.get("endpoint") or next(e["url"] for e in details["endpoints"] if e.get("isAccessible"))
    assert endpoint.startswith("https://") and endpoint.split("/")[2].endswith(".memory.redis.io"), "Unexpected data-plane host"
    instance = AgentMemory(endpoint, store_id=store, api_key=token, timeout_ms=30000, retry_config=None)
    deadline = time.monotonic() + 90
    while True:
        try:
            instance.list_sessions(limit=1, include_all=True)
            break
        except Exception:
            if time.monotonic() >= deadline:
                instance.__exit__(None, None, None)
                raise
            time.sleep(2)
    session = "validation-" + uuid.uuid4().hex[:20]
    response = instance.add_session_event(session_id=session, actor_id="validation-user", role="USER",
                                          content=[{"text": "Synthetic test context: I prefer unsweetened coffee."}],
                                          created_at=datetime.now(timezone.utc))
    event_id = response.event.event_id
    assert event_id, "Synthetic session event was not created"
    return {"client": instance, "session": session, "event": event_id, "endpoint": endpoint, "memory": None}


def check_context(context):
    response = context["client"].get_session_memory(session_id=context["session"])
    assert any(e.event_id == context["event"] for e in response.events), "Synthetic session context did not survive configuration updates"
    if context.get("memory"):
        memory = context["client"].get_long_term_memory(memory_id=context["memory"])
        assert memory.id == context["memory"] and memory.text == "Synthetic durable fact: the user prefers unsweetened coffee.", "Long-term context did not survive configuration updates"


def run_lifecycle(database_id, binary, api, results):
    fixture = Fixture(database_id, binary, api)
    results.data["fixture_name"] = fixture.name
    context = None
    try:
        if not results.case("terraform-create", lambda: fixture.apply({STORE: ["create"], KEY: ["create"]}) and {"created": True}):
            return
        results.data["store_id"], results.data["key_id"] = fixture.identities()[:2]
        results.case("unchanged-reapply", lambda: fixture.plan({}) and {"changes": 0})
        results.case("store-and-key-import", lambda: import_check(fixture))
        if os.environ.get("VALIDATION_SUITE") == "minimum":
            results.case("minimum-terraform-update", lambda: update_check(fixture, "short_term_ttl_seconds", 43200))
            return
        if os.environ.get("VALIDATE_DATA_PLANE", "1") == "1":
            try:
                context = make_context(fixture)
                results.case("synthetic-context-read", lambda: check_context(context))
                def long_term():
                    memory_id = "memory-" + uuid.uuid4().hex[:20]
                    response = context["client"].bulk_create_long_term_memories(memories=[{
                        "id": memory_id, "text": "Synthetic durable fact: the user prefers unsweetened coffee.",
                        "owner_id": "validation-user", "session_id": context["session"], "memory_type": "semantic"}])
                    assert not response.errors and memory_id in response.created, "Long-term memory creation failed or partially succeeded"
                    context["memory"] = memory_id
                    check_context(context)
                results.case("synthetic-long-term-memory-create-and-read", long_term)
            except Exception as exc:
                results.data["cases"].append({"name": "synthetic-context-create", "status": "failed", "exception_type": type(exc).__name__})
        results.case("ttl-update-preserves-identity", lambda: update_check(fixture, "short_term_ttl_seconds", 43200))
        results.case("out-of-band-drift-reconciliation", lambda: drift_check(fixture))
        results.case("inactive-definitions-and-empty-list-clearing", lambda: advanced_check(fixture))
        if context:
            results.case("context-survives-store-updates", lambda: check_context(context))
        for name, mutate, reject, hints in negative_cases():
            results.case(name, lambda m=mutate, r=reject, h=hints: negative_update(fixture, m, r, h))
        results.case("custom-type-add-and-strategy-update", lambda: custom_types_check(fixture))
        candidate = copy.deepcopy(fixture.config)
        candidate["database_id"] = 0
        results.case("database-change-blocked-without-replacement", lambda: blocked_change(fixture, candidate))
        candidate = copy.deepcopy(fixture.config)
        candidate["custom_memory_types"] = candidate["custom_memory_types"][:1]
        results.case("custom-type-removal-blocked-without-replacement", lambda: blocked_change(fixture, candidate))
        if context:
            results.case("context-survives-invalid-inputs-and-custom-types", lambda: check_context(context))
        before = fixture.identities()
        fixture.key_name += "-rotated"
        fixture.write()
        def rotate():
            fixture.apply({KEY: ["create", "delete"]})
            after = fixture.identities()
            assert after[0] == before[0] and after[1] != before[1] and after[2] != before[2], "Key replacement changed the store or failed to rotate the secret"
            keys = api.request("/memory-stores/" + before[0] + "/api-keys").get("apiKeys", [])
            assert not any(k["apiKeyId"] == before[1] for k in keys), "Replaced key remains active in metadata"
            fixture.plan({})
            if context:
                from agent_memory_auth_probe import denied
                from redis_agent_memory import AgentMemory
                deadline = time.monotonic() + 60
                while not denied(lambda: context["client"].list_sessions(limit=1, include_all=True)):
                    assert time.monotonic() < deadline, "Replaced runtime secret remained accepted after revocation deadline"
                    time.sleep(2)
                context["client"].__exit__(None, None, None)
                context["client"] = AgentMemory(context["endpoint"], store_id=after[0], api_key=after[2], timeout_ms=30000, retry_config=None)
                check_context(context)
        results.case("runtime-key-replacement-only", rotate)
    finally:
        if context:
            try:
                context["client"].__exit__(None, None, None)
            except Exception:
                pass
        def cleanup():
            errors = fixture.cleanup()
            assert not errors, "Terraform cleanup needed fallback API reconciliation"
        results.data["cleanup_verified"] = results.case("terraform-fixture-destroy-and-api-absence", cleanup)
        results.save()


def main():
    assert os.environ.get("LIVE_VALIDATION_CONFIRM") == "isolated-qa-only", "Explicit isolated-QA opt-in is required"
    database_id = os.environ["AGENT_MEMORY_TEST_DATABASE_ID"]
    binary = os.environ["CANDIDATE_PROVIDER_BINARY"]
    report = Results(os.environ.get("LIVE_VALIDATION_REPORT", "live-validation-results.json"))
    report.data["binary_sha256"] = hashlib.sha256(Path(binary).read_bytes()).hexdigest()
    api = Api()
    try:
        run_lifecycle(database_id, binary, api, report)
    finally:
        report.save()
    assert report.data["cleanup_verified"], "Fixture cleanup not verified"
    assert not any(r["status"] == "failed" for r in report.data["cases"]), "One or more live validation cases failed; inspect the non-sensitive JSON report"


if __name__ == "__main__":
    main()
