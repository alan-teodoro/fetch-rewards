import importlib.util
import json
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import tempfile
import threading
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("provider_live_validation", ROOT / "scripts/internal/provider_live_validation.py")
live = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(live)


class MockCloud:
    def __init__(self):
        self.store = None
        self.keys = []
        self.counter = 0
        self.partial_invalid_update = False
        self.reject_quota = False
        self.task_error = None
        cloud = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def send(self, payload, status=200):
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                if status != 204:
                    self.wfile.write(json.dumps(payload).encode())

            def body(self):
                return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")

            def do_GET(self):
                if self.path == "/memory-stores":
                    return self.send({"data": [cloud.store] if cloud.store else []})
                if self.path.startswith("/tasks/"):
                    if cloud.task_error:
                        error = cloud.task_error
                        cloud.task_error = None
                        return self.send(error)
                    return self.send({"taskId": "fixture", "status": "processing-completed", "response": {"resource": {"storeId": "store-1"}}})
                if self.path.endswith("/api-keys"):
                    return self.send({"apiKeys": cloud.keys})
                if self.path == "/memory-stores/store-1" and cloud.store:
                    return self.send(cloud.store)
                self.send({"message": "not found"}, 404)

            def do_POST(self):
                body = self.body()
                if self.path.endswith("/api-keys"):
                    cloud.counter += 1
                    cloud.keys.append({"apiKeyId": f"key-{cloud.counter}", "keyName": body["keyName"], "createdAt": 1234, "obfuscatedToken": "FAKE"})
                    return self.send({"apiKey": f"FAKE-SECRET-{cloud.counter}"})
                cloud.store = dict(body, storeId="store-1", databaseId=str(body["databaseId"]), status="READY", extractionStrategy="INSTRUCT")
                self.send({"taskId": "fixture"})

            def do_PATCH(self):
                body = self.body()
                if body.get("shortMemory", {}).get("ttlSeconds", 1) < 0:
                    if cloud.partial_invalid_update:
                        cloud.store["name"] = body["name"]
                    return self.send({"message": "Invalid ttlSeconds"}, 400)
                additions = body.pop("addCustomMemoryTypes", [])
                if cloud.reject_quota and len(cloud.store.get("customMemoryTypes", [])) + len(additions) > 3:
                    cloud.task_error = {"taskId": "fixture", "status": "processing-completed", "response": {
                        "error": {"code": "FAILED"}, "additionalInfo": "Custom memory type quota reached"}}
                    return self.send({"taskId": "fixture"})
                if additions:
                    cloud.store.setdefault("customMemoryTypes", []).extend(additions)
                for update in body.pop("updateCustomMemoryTypeStrategies", []):
                    for memory_type in cloud.store.get("customMemoryTypes", []):
                        if memory_type["name"] == update["typeName"]:
                            memory_type["extractionStrategy"].update({k: v for k, v in update.items() if k != "typeName"})
                cloud.store.update(body)
                self.send({"taskId": "fixture"})

            def do_DELETE(self):
                if "/api-keys/" in self.path:
                    cloud.keys[:] = [k for k in cloud.keys if k["apiKeyId"] != self.path.rsplit("/", 1)[1]]
                    return self.send({}, 204)
                cloud.store = None
                cloud.keys.clear()
                self.send({"taskId": "fixture"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class BinaryHarnessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary = Path(os.environ.get("MOCK_PROVIDER_BINARY", ROOT / ".generated/consolidated-review-20261017/terraform-provider-rediscloud"))
        if not cls.binary.is_file():
            raise unittest.SkipTest("Build the candidate and set MOCK_PROVIDER_BINARY to exercise the real Terraform CLI")

    def environment(self, cloud):
        return patch.dict(os.environ, {"REDISCLOUD_ACCESS_KEY": "fake", "REDISCLOUD_SECRET_KEY": "fake",
                                     "REDISCLOUD_URL": f"http://127.0.0.1:{cloud.server.server_port}",
                                     "VALIDATION_SUITE": "minimum", "VALIDATE_DATA_PLANE": "0"})



class LiveHarnessTest(BinaryHarnessTest):
    def test_actual_terraform_lifecycle_import_update_and_cleanup(self):
        with MockCloud() as cloud, self.environment(cloud), tempfile.TemporaryDirectory() as temp:
            report = live.Results(Path(temp) / "result.json")
            live.run_lifecycle("123", self.binary, live.Api(), report)
            self.assertTrue(report.data["cleanup_verified"])
            self.assertFalse([r for r in report.data["cases"] if r["status"] != "passed"])
            self.assertIsNone(cloud.store)
            self.assertFalse(cloud.keys)
            serialized = json.dumps(report.data)
            self.assertNotIn("FAKE-SECRET", serialized)
            self.assertNotIn("terraform.tfstate", serialized)

    def test_advanced_inactive_definitions_empty_lists_and_custom_type_updates(self):
        with MockCloud() as cloud, self.environment(cloud):
            fixture = live.Fixture("123", self.binary, live.Api())
            try:
                fixture.apply({live.STORE: ["create"], live.KEY: ["create"]})
                identity = fixture.identities()
                live.advanced_check(fixture)
                live.custom_types_check(fixture)
                self.assertEqual(fixture.identities(), identity)
            finally:
                self.assertFalse(fixture.cleanup())

    def test_rejected_update_checks_partial_mutation_and_restores_fixture(self):
        with MockCloud() as cloud, self.environment(cloud):
            fixture = live.Fixture("123", self.binary, live.Api())
            try:
                fixture.apply({live.STORE: ["create"], live.KEY: ["create"]})
                mutate = lambda cfg: cfg.__setitem__("short_term_ttl_seconds", -1)
                result = live.negative_update(fixture, mutate, hints=("ttl",))
                self.assertTrue(result["rejected"])
                self.assertTrue(result["remote_unchanged"])
                cloud.partial_invalid_update = True
                with self.assertRaisesRegex(AssertionError, "partially mutated"):
                    live.negative_update(fixture, mutate, hints=("ttl",))
                self.assertEqual(cloud.store["name"], fixture.name)
            finally:
                self.assertFalse(fixture.cleanup())
            self.assertIsNone(cloud.store)


class CleanupGuardTest(unittest.TestCase):
    def test_wrong_database_intent_is_rejected_before_any_api_call(self):
        import sys
        with patch.dict(sys.modules, {"provider_live_validation": live}):
            spec = importlib.util.spec_from_file_location("provider_live_cleanup", ROOT / "scripts/internal/provider_live_cleanup.py")
            cleanup = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cleanup)
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {
            "LIVE_VALIDATION_CONFIRM": "isolated-qa-only", "AGENT_MEMORY_TEST_DATABASE_ID": "123", "LIVE_RESULTS_DIRECTORY": temp,
        }):
            (Path(temp) / "intent-other.json").write_text(json.dumps({"fixture": "tfacc-live-other", "database_id": "456", "names": ["other"]}))
            with self.assertRaisesRegex(AssertionError, "another database"):
                cleanup.main()


class TaskProtocolTest(unittest.TestCase):
    def test_async_error_retains_evidence_without_treating_it_as_success(self):
        api = live.Api("http://unused")
        api.request = lambda *_args: {"status": "processing-completed", "response": {
            "error": {"code": "FAILED"}, "additionalInfo": "Invalid field"}}
        with self.assertRaises(live.ApiError) as raised:
            api.wait({"taskId": "owned"})
        self.assertEqual(raised.exception.status, 422)
        self.assertEqual(raised.exception.payload["additionalInfo"], "Invalid field")


class ControlledFaultHarnessTest(BinaryHarnessTest):
    def test_all_controlled_faults_with_real_terraform(self):
        import sys
        with patch.dict(sys.modules, {"provider_live_validation": live}):
            fault_spec = importlib.util.spec_from_file_location("provider_live_faults", ROOT / "scripts/internal/provider_live_faults.py")
            faults = importlib.util.module_from_spec(fault_spec)
            fault_spec.loader.exec_module(faults)
        for mode in ("create-response", "task-result", "read-id", "read-error", "key-response", "update-read-error"):
            with self.subTest(mode=mode), MockCloud() as cloud, self.environment(cloud):
                evidence = faults.run_fault(live.Api(), "123", self.binary, mode)
                self.assertEqual(evidence["counts_before_explicit_cleanup"]["store_create"], 1)
                self.assertEqual(evidence["counts_before_explicit_cleanup"]["store_delete"], 0)
                self.assertIsNone(cloud.store)
                self.assertFalse(cloud.keys)


class ContractHarnessTest(BinaryHarnessTest):
    def test_actual_async_error_reaches_provider_and_update_is_atomic(self):
        import sys
        with patch.dict(sys.modules, {"provider_live_validation": live}):
            import_path = str(ROOT / "scripts" / "internal")
            sys.path.insert(0, import_path)
            try:
                spec = importlib.util.spec_from_file_location("provider_live_contract", ROOT / "scripts/internal/provider_live_contract.py")
                contract = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(contract)
                with MockCloud() as cloud, self.environment(cloud):
                    cloud.reject_quota = True
                    evidence = contract.contract_case(live.Api(), "123", self.binary, "cumulative-custom-type-quota")
                    self.assertFalse(evidence["accepted_by_current_service"])
                    self.assertTrue(evidence["remote_unchanged"])
                    self.assertTrue(evidence["async_additional_info_observed"])
                    self.assertTrue(evidence["provider_preserved_async_additional_info"])
                    self.assertIsNone(cloud.store)
            finally:
                sys.path.remove(import_path)
