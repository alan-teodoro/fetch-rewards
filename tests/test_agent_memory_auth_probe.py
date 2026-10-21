import importlib.util
import contextlib
import io
import os
from pathlib import Path
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "auth_probe", Path(__file__).resolve().parents[1] / "scripts/internal/agent_memory_auth_probe.py"
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class AuthProbeTests(unittest.TestCase):
    def test_control_plane_headers_and_error_body_redaction(self):
        failure = probe.HTTPError(
            "https://api.redislabs.com/v1/memory-stores", 403, "Forbidden", {},
            io.BytesIO(b'FAKE_CREDENTIAL_ECHOED_BY_API'),
        )
        settings = {"REDISCLOUD_ACCESS_KEY": "FAKE_ACCESS", "REDISCLOUD_SECRET_KEY": "FAKE_SECRET", "REDISCLOUD_URL": "https://api.redislabs.com/v1"}
        with patch.dict(os.environ, settings), patch.object(probe, "urlopen", side_effect=failure) as call:
            with self.assertRaises(probe.ProbeError) as raised:
                probe.ControlPlane().request("/memory-stores")
        request = call.call_args.args[0]
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertEqual(request.get_header("User-agent"), "rediscloud-provider-readiness-tests/1.0")
        self.assertEqual(str(raised.exception), "Control-plane request failed: HTTP 403")
        self.assertNotIn("FAKE_CREDENTIAL", str(raised.exception))

    def test_cli_emits_status_without_echoing_sdk_response(self):
        class Failure(Exception):
            status_code = 401

        stderr = io.StringIO()
        with patch.object(probe, "main", side_effect=Failure("FAKE_SECRET_IN_SDK_BODY")):
            with contextlib.redirect_stderr(stderr):
                self.assertEqual(probe.cli(), 1)
        self.assertIn("HTTP 401", stderr.getvalue())
        self.assertNotIn("FAKE_SECRET", stderr.getvalue())

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
