#!/usr/bin/env python3
"""Controlled response faults for owned fixtures, never faults on shared API traffic."""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time

from provider_live_validation import Api, ApiError, Fixture, KEY, Results, STORE


class FixtureProxy:
    def __init__(self, api, fixture, mode):
        self.api, self.fixture, self.mode = api, fixture, mode
        self.injected = False
        self.async_details = []
        self.owned_ids, self.tasks = set(), set()
        self.counts = {"store_create": 0, "key_create": 0, "store_delete": 0, "store_update": 0}
        self.lock = threading.Lock()
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def respond(self, status, payload):
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def handle_request(self):
                method, path = self.command, self.path
                data = None
                if method in ("POST", "PATCH"):
                    data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                store_post = method == "POST" and path == "/memory-stores"
                key_post = method == "POST" and path.endswith("/api-keys")
                store_path = path.startswith("/memory-stores/") and "/" not in path[len("/memory-stores/"):]
                with proxy.lock:
                    if method != "GET":
                        if store_post:
                            assert data.get("name") in fixture.intent_names
                            assert str(data.get("databaseId")) == fixture.database_id
                        else:
                            assert path.startswith("/memory-stores/")
                            assert path.split("/")[2] in proxy.owned_ids
                            if key_post:
                                assert data.get("keyName", "").startswith(fixture.name)
                    try:
                        payload = api.request(path, method, data)
                    except ApiError as exc:
                        return self.respond(exc.status, exc.payload)
                    if store_post:
                        proxy.counts["store_create"] += 1
                        if payload.get("taskId"):
                            proxy.tasks.add(str(payload["taskId"]))
                    if key_post:
                        proxy.counts["key_create"] += 1
                    if store_path and method == "DELETE":
                        proxy.counts["store_delete"] += 1
                    if store_path and method == "PATCH":
                        proxy.counts["store_update"] += 1
                    resource = (payload.get("response") or {}).get("resource") or {}
                    extra = (payload.get("response") or {}).get("additionalInfo")
                    if isinstance(extra, str) and extra:
                        proxy.async_details.append(extra)
                    for value in (payload.get("storeId"), resource.get("storeId")):
                        if value:
                            proxy.owned_ids.add(str(value))
                    if not proxy.injected:
                        lose = ((mode == "create-response" and store_post)
                                or (mode == "key-response" and key_post)
                                or (mode in ("read-id", "read-error") and method == "GET" and store_path)
                                or (mode == "update-read-error" and method == "GET" and store_path and proxy.counts["store_update"] > 0))
                        if lose:
                            proxy.injected = True
                            if mode == "read-id":
                                payload.pop("storeId", None)
                            else:
                                return self.respond(503, {"message": "Controlled owned-fixture response loss"})
                        elif mode == "task-result" and path.startswith("/tasks/") and path.rsplit("/", 1)[1] in proxy.tasks and resource.get("storeId"):
                            proxy.injected = True
                            payload["response"].pop("resource", None)
                    self.respond(200, payload)

            def dispatch(self):
                try:
                    self.handle_request()
                except Exception:
                    self.respond(500, {"message": "Owned-fixture proxy assertion failed"})

            do_GET = do_POST = do_PATCH = do_DELETE = dispatch

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        self.fixture.environment["REDISCLOUD_URL"] = f"http://127.0.0.1:{self.server.server_port}"
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def find_owned(api, fixture):
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        stores = [s for s in api.stores(fixture.database_id) if s.get("name") == fixture.name]
        assert len(stores) <= 1, "Fault recovery created duplicate stores"
        if stores and stores[0].get("status") == "READY":
            return stores[0]["storeId"]
        time.sleep(1)
    raise RuntimeError("Accepted fixture store did not become READY")


def run_fault(api, database_id, binary, mode):
    fixture = Fixture(database_id, binary, api)
    try:
        with FixtureProxy(api, fixture, mode) as proxy:
            fixture.plan({STORE: ["create"], KEY: ["create"]})
            if mode == "update-read-error":
                fixture.command("apply", "-input=false", "-no-color", "checked.tfplan")
                original = fixture.identities()
                fixture.config["short_term_ttl_seconds"] = 43200
                fixture.write()
                fixture.plan({STORE: ["update"]})
                response = fixture.command("apply", "-input=false", "-no-color", "checked.tfplan", allowed=(0, 1))
                assert response.returncode == 1, "Update read failure did not surface as an error"
                fixture.apply({})
                assert fixture.identities() == original, "Update read failure changed identity or runtime secret"
                assert fixture.values()[STORE]["short_term_ttl_seconds"] == 43200, "Update read recovery did not refresh accepted configuration"
            else:
                response = fixture.command("apply", "-input=false", "-no-color", "checked.tfplan", allowed=(0, 1))
                owned_id = find_owned(api, fixture)
                proxy.owned_ids.add(owned_id)
                if mode in ("read-id", "read-error"):
                    assert response.returncode == 0, "Acknowledged creation was treated as a failure and could taint the store"
                    assert fixture.identities()[0] == owned_id, "Acknowledged store identity was not saved"
                else:
                    assert response.returncode == 1, "Lost response did not surface as an error"
                    if mode in ("create-response", "task-result"):
                        fixture.command("import", "-input=false", STORE, owned_id)
                    else:
                        keys = api.request("/memory-stores/" + owned_id + "/api-keys").get("apiKeys", [])
                        assert len(keys) == 1 and keys[0]["keyName"] == fixture.key_name, "Lost key response could not be positively reconciled"
                        api.request("/memory-stores/" + owned_id + "/api-keys/" + keys[0]["apiKeyId"], "DELETE")
                fixture.apply()
                assert fixture.identities()[0] == owned_id, "Recovery changed the store identity"
            fixture.plan({})
            assert proxy.injected, "The controlled fault was not exercised"
            assert proxy.counts["store_create"] == 1, "Recovery duplicated the store"
            assert proxy.counts["store_delete"] == 0, "Recovery deleted the acknowledged store"
            assert proxy.counts["key_create"] == (2 if mode == "key-response" else 1), "Recovery created an unexpected number of runtime keys"
            return {"fault_injected": True, "counts_before_explicit_cleanup": dict(proxy.counts), "store_id": fixture.identities()[0]}
    finally:
        # Cleanup is direct, outside fault injection, and verified against the API.
        fixture.environment["REDISCLOUD_URL"] = api.base
        errors = fixture.cleanup()
        assert not errors, "Fault fixture cleanup required fallback API reconciliation"


def main():
    assert os.environ.get("LIVE_VALIDATION_CONFIRM") == "isolated-qa-only", "Explicit isolated-QA opt-in is required"
    results = Results(os.environ["LIVE_VALIDATION_REPORT"])
    api = Api()
    for mode in ("create-response", "task-result", "read-id", "read-error", "key-response", "update-read-error"):
        results.case(mode, lambda m=mode: run_fault(api, os.environ["AGENT_MEMORY_TEST_DATABASE_ID"], os.environ["CANDIDATE_PROVIDER_BINARY"], m))
    results.data["cleanup_verified"] = not any(c["status"] == "failed" for c in results.data["cases"])
    results.save()
    assert results.data["cleanup_verified"], "Controlled fault checks failed; inspect assertion report"


if __name__ == "__main__":
    main()
