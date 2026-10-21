"""Run with the pinned optional SDK installed; no network/cloud resources used."""

import importlib.util
from pathlib import Path
import unittest


sdk_available = importlib.util.find_spec("redis_agent_memory") is not None


@unittest.skipUnless(sdk_available, "pinned data-plane SDK required; protected QA job runs this test")
class AuthProbeSDKTests(unittest.TestCase):
    def test_sdk_protocol_authentication_and_fixture_cleanup(self):
        import httpx
        from redis_agent_memory import AgentMemory

        spec = importlib.util.spec_from_file_location(
            "auth_probe", Path(__file__).resolve().parents[1] / "scripts/internal/agent_memory_auth_probe.py"
        )
        probe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(probe)

        class Control:
            def __init__(self):
                self.counter = 0
                self.keys = {sid: [{"apiKeyId": "existing", "keyName": "customer-key"}] for sid in ("store-a", "store-b")}

            def request(self, path, method="GET", data=None):
                if path == "/memory-stores":
                    return {"data": [
                        {"name": name, "storeId": sid, "databaseId": "123", "status": "READY"}
                        for name, sid in (("readiness-agent", "store-a"), ("readiness-support-agent", "store-b"))
                    ]}
                sid = path.split("/")[2]
                if method == "POST":
                    self.counter += 1
                    key_id = f"fixture-{self.counter}"
                    self.keys[sid].append({"apiKeyId": key_id, "keyName": data["keyName"]})
                    return {"apiKey": f"FAKE-{sid}-{key_id}"}
                if method == "DELETE":
                    self.keys[sid] = [k for k in self.keys[sid] if k["apiKeyId"] != path.rsplit("/", 1)[1]]
                    return {}
                if path.endswith("api-keys"):
                    return {"apiKeys": list(self.keys[sid])}
                return {"databaseId": "123", "endpoint": "https://qa.memory.redis.io"}

        control = Control()
        requests = []

        def handler(request):
            requests.append(request)
            self.assertEqual(request.url.params.get("includeAll"), "true")
            self.assertEqual(request.url.params.get("limit"), "1")
            sid = next(s for s in control.keys if s in request.url.path)
            token = request.headers.get("Authorization", "")
            own = any(token == f"Bearer FAKE-{sid}-{k['apiKeyId']}" for k in control.keys[sid])
            if own:
                return httpx.Response(200, json={"items": [], "total": 0}, request=request)
            status = 403 if any(token == f"Bearer FAKE-{other}-{k['apiKeyId']}" for other in control.keys for k in control.keys[other]) else 401
            return httpx.Response(status, json={"message": "FAKE_CREDENTIAL_RESPONSE"}, request=request)

        with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
            def make_client(endpoint, **kwargs):
                return AgentMemory(endpoint, client=transport, **kwargs)

            probe.run_probe(control, make_client, "123", "sdk-fixture")

        self.assertEqual(len(requests), 8)
        self.assertEqual(control.counter, 3)
        self.assertTrue(all(rows == [{"apiKeyId": "existing", "keyName": "customer-key"}] for rows in control.keys.values()))


if __name__ == "__main__":
    unittest.main()
