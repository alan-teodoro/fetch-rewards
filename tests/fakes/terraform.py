#!/usr/bin/env python3
"""Simulate terraform for workflow regressions using local files only."""

import hashlib
import json
import os
import pathlib
import re
import sys

args = sys.argv[1:]
stack = pathlib.Path(next(a.split("=", 1)[1] for a in args if a.startswith("-chdir=")))
command = args[1]
backend = stack / ".mock-backend"
if command == "init":
    backend.write_text(
        next(
            a.split("key=", 1)[1] for a in args if a.startswith("-backend-config=key=")
        )
    )
    if os.environ.get("MOCK_OVERRIDE_LOCK") and stack.name == "agent-memory":
        lock = stack / ".terraform.lock.hcl"
        raw = lock.read_text()
        raw = re.sub(
            r'^provider "registry\.terraform\.io/redislabs/rediscloud" \{\n.*?^\}\n?',
            "",
            raw,
            flags=re.M | re.S,
        )
        lock.write_text(
            raw
            + '\nprovider "registry.terraform.io/redislabs/rediscloud" {\n  version = "2.19.1"\n}\n'
        )
    if os.environ.get("MOCK_REWRITE_LOCK"):
        (stack / ".terraform.lock.hcl").write_text(
            'provider "registry.terraform.io/hashicorp/random" {\n version = "9.9.9"\n}\n'
            if os.environ["MOCK_REWRITE_LOCK"] == "random"
            else "unapproved dependency change"
        )
    sys.exit(0)
key = backend.read_text()
kind = stack.name
if command == "state":
    if key not in json.loads(os.environ.get("MOCK_EMPTY_STATES", "[]")):
        print("managed.example")
    sys.exit(0)
if command == "plan":
    variables = pathlib.Path(
        next(a.split("=", 1)[1] for a in args if a.startswith("-var-file="))
    )
    variables_hash = hashlib.sha256(variables.read_bytes()).hexdigest()
    fixtures = json.loads(os.environ["MOCK_CHANGES"])
    resource_type = {
        "subscription": "rediscloud_subscription",
        "database": "rediscloud_subscription_database",
        "agent-memory": "rediscloud_agent_memory",
    }[kind]
    override = fixtures.get(key, fixtures.get(kind, {}))
    actions = ["delete"] if "-destroy" in args else override.get("actions", ["no-op"])
    before = override.get("before", "existing")
    after = override.get("after", "existing")
    before = before if isinstance(before, dict) else {"name": before}
    after = after if isinstance(after, dict) else {"name": after}
    plan = {
        "state_key": key,
        "resource_changes": [
            {
                "mode": "managed",
                "type": resource_type,
                "address": resource_type + ".this",
                "change": {
                    "actions": actions,
                    "before": before,
                    "after": after,
                    "after_unknown": override.get("after_unknown", {}),
                    "before_sensitive": override.get("before_sensitive", {}),
                    "after_sensitive": override.get("after_sensitive", {}),
                },
            }
        ],
        "output_changes": override.get("output_changes", {}),
    }
    name = next(a.split("=", 1)[1] for a in args if a.startswith("-out="))
    (stack / name).write_text(json.dumps(plan))
elif command == "show":
    print((stack / args[-1]).read_text())
    sys.exit(0)
elif command == "apply":
    key = json.loads((stack / args[-1]).read_text())["state_key"]
else:
    raise SystemExit("Unsupported mock command: " + command)
with open(os.environ["MOCK_EVENTS"], "a") as f:
    f.write(
        json.dumps(
            {
                "command": command,
                "kind": kind,
                "state_key": key,
                **({"variables_hash": variables_hash} if command == "plan" else {}),
            }
        )
        + "\n"
    )
if command == "apply" and os.environ.get("MOCK_FAIL_APPLY") == kind:
    sys.exit(2)
