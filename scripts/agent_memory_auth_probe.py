#!/usr/bin/env python3
"""Opt-in QA authentication probe; emits no credentials or SDK error bodies."""

import json
import os
import sys
import time
import uuid
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class ProbeError(Exception):
    pass


class ControlPlane:
    def request(self, path, method="GET", data=None):
        base = os.environ.get("REDISCLOUD_URL") or "https://api.redislabs.com/v1"
        request = Request(
            base.rstrip("/") + path,
            method=method,
            data=None if data is None else json.dumps(data).encode(),
            headers={
                "x-api-key": os.environ["REDISCLOUD_ACCESS_KEY"],
                "x-api-secret-key": os.environ["REDISCLOUD_SECRET_KEY"],
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=25) as response:
                payload = response.read()
                return json.loads(payload) if payload else {}
        except HTTPError as error:
            raise ProbeError(f"Control-plane request failed: HTTP {error.code}") from None


def denied(operation):
    """A service error or timeout must never count as an authorization denial."""
    try:
        operation()
    except Exception as error:
        status = getattr(error, "status_code", None)
        if status in (401, 403):
            return True
        raise ProbeError("Authorization check returned an unexpected error; details omitted") from None
    return False


def run_probe(control, make_client, database_id, prefix):
    stores = control.request("/memory-stores").get("data", [])
    targets = []
    for name in ("readiness-agent", "readiness-support-agent"):
        matches = [s for s in stores if s.get("name") == name and str(s.get("databaseId")) == database_id]
        if len(matches) != 1 or matches[0].get("status") != "READY":
            raise ProbeError("Both configured QA stores must exist and be READY")
        store_id = matches[0]["storeId"]
        details = control.request(f"/memory-stores/{store_id}")
        if str(details.get("databaseId")) != database_id:
            raise ProbeError("QA database ownership check failed")
        endpoint = details.get("endpoint") or next(
            (e["url"] for e in details.get("endpoints", []) if e.get("isAccessible")), ""
        )
        parsed = urlparse(endpoint)
        if parsed.scheme != "https" or not (parsed.hostname or "").endswith(".memory.redis.io"):
            raise ProbeError("Expected an HTTPS Redis Agent Memory endpoint")
        targets.append((store_id, endpoint))

    fixtures = []
    clients = []

    def keys(store):
        return control.request(f"/memory-stores/{store}/api-keys").get("apiKeys", [])

    def create(target, suffix):
        store, endpoint = target
        name = prefix + "-" + suffix
        before = {k["apiKeyId"] for k in keys(store)}
        if any(k.get("keyName") == name for k in keys(store)):
            raise ProbeError("Fixture key name already exists; reconcile before retrying")
        # Record intent before POST so cleanup can reconcile a lost response too.
        fixtures.append((store, name, before))
        response = control.request(f"/memory-stores/{store}/api-keys", "POST", {"keyName": name})
        candidates = [k for k in keys(store) if k["apiKeyId"] not in before and k.get("keyName") == name]
        if len(candidates) != 1 or not response.get("apiKey"):
            raise ProbeError("Created key could not be resolved; cleanup will reconcile its metadata")
        instance = make_client(endpoint, store_id=store, api_key=response["apiKey"], timeout_ms=15000, retry_config=None)
        clients.append(instance)
        return instance, response["apiKey"], candidates[0]["apiKeyId"]

    try:
        first, first_secret, first_id = create(targets[0], "a")
        second, second_secret, _ = create(targets[1], "b")
        first.list_sessions(limit=1)
        second.list_sessions(limit=1)
        for target, secret in ((targets[0], second_secret), (targets[1], first_secret)):
            cross = make_client(target[1], store_id=target[0], api_key=secret, timeout_ms=15000, retry_config=None)
            clients.append(cross)
            if not denied(lambda: cross.list_sessions(limit=1)):
                raise ProbeError("A runtime key was accepted by the other store")
        rotated, _, _ = create(targets[0], "rotated")
        rotated.list_sessions(limit=1)
        control.request(f"/memory-stores/{targets[0][0]}/api-keys/{first_id}", "DELETE")
        deadline = time.monotonic() + 60
        while not denied(lambda: first.list_sessions(limit=1)):
            if time.monotonic() >= deadline:
                raise ProbeError("Revoked runtime key remained accepted after 60 seconds")
            time.sleep(2)
        rotated.list_sessions(limit=1)
        second.list_sessions(limit=1)
    finally:
        cleanup_failed = False
        for store, name, before in reversed(fixtures):
            try:
                candidates = [k for k in keys(store) if k["apiKeyId"] not in before and k.get("keyName") == name]
                if len(candidates) > 1:
                    cleanup_failed = True
                    continue
                for key in candidates:
                    control.request(f"/memory-stores/{store}/api-keys/{key['apiKeyId']}", "DELETE")
                if any(k.get("keyName") == name and k["apiKeyId"] not in before for k in keys(store)):
                    cleanup_failed = True
            except Exception:
                cleanup_failed = True
        for instance in clients:
            try:
                instance.__exit__(None, None, None)
            except Exception:
                cleanup_failed = True
        if cleanup_failed:
            raise ProbeError("Fixture cleanup incomplete; reconcile the logged fixture prefix before retrying") from None


def main():
    from redis_agent_memory import AgentMemory

    database_id = os.environ["AGENT_MEMORY_TEST_DATABASE_ID"]
    if not database_id.isdigit():
        raise ProbeError("A positive QA database ID is required")
    prefix = "readiness-auth-" + uuid.uuid4().hex[:16]
    print("Authentication probe fixture prefix: " + prefix, flush=True)
    run_probe(ControlPlane(), AgentMemory, database_id, prefix)
    print("PASS: both keys authenticate; cross-store access denied; revoked key rejected; replacement and unrelated key work; fixture keys removed")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # SDK exceptions may embed request headers or response bodies.
        print("FAIL: QA authentication probe did not complete. Credentials/error bodies omitted; inspect the fixture prefix for cleanup.", file=sys.stderr)
        sys.exit(1)
