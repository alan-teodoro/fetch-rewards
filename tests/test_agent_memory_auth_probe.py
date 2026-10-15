import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    "auth_probe", Path(__file__).resolve().parents[1] / "scripts/agent_memory_auth_probe.py"
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class AuthProbeTests(unittest.TestCase):
    def test_server_error_is_not_an_authentication_denial(self):
        class Failure(Exception):
            status_code = 503

        def request():
            raise Failure("FAKE_SECRET_MUST_NOT_ESCAPE")

        with self.assertRaises(probe.ProbeError) as raised:
            probe.denied(request)
        self.assertNotIn("FAKE_SECRET", str(raised.exception))

    def test_lost_key_response_is_reconciled_without_deleting_existing_key(self):
        class Control:
            def __init__(self):
                self.created = False
                self.deleted = []

            def request(self, path, method="GET", data=None):
                if path == "/memory-stores":
                    return {"data": [
                        {"name": name, "storeId": sid, "databaseId": "123", "status": "READY"}
                        for name, sid in (("readiness-agent", "store-a"), ("readiness-support-agent", "store-b"))
                    ]}
                if method == "POST":
                    self.created = True
                    raise OSError("FAKE_SECRET_LOST_RESPONSE")
                if method == "DELETE":
                    self.deleted.append(path)
                    self.created = False
                    return {}
                if path.endswith("api-keys"):
                    rows = [{"apiKeyId": "existing", "keyName": "customer-key"}]
                    if self.created:
                        rows.append({"apiKeyId": "new", "keyName": "unique-prefix-a"})
                    return {"apiKeys": rows}
                return {"databaseId": "123", "endpoint": "https://aws-us-east-1.memory.redis.io"}

        control = Control()
        with self.assertRaises(OSError):
            probe.run_probe(control, None, "123", "unique-prefix")
        self.assertEqual(control.deleted, ["/memory-stores/store-a/api-keys/new"])


if __name__ == "__main__":
    unittest.main()
