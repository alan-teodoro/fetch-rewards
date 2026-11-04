#!/usr/bin/env python3
"""Simulate one root's Terraform CLI; no infrastructure or state contents."""

import json
import os
import pathlib
import sys

args = sys.argv[1:]
stack = pathlib.Path(args[0].split("=", 1)[1])
command = args[1]
backend = stack / ".mock-backend"
if command == "init":
    backend.write_text(
        next(
            a.split("key=", 1)[1] for a in args if a.startswith("-backend-config=key=")
        )
    )
    if os.environ.get("MOCK_REWRITE_LOCK"):
        (stack / ".terraform.lock.hcl").write_text("unapproved dependencies")
    sys.exit(0)
key = backend.read_text()
if command == "plan":
    variables = pathlib.Path(
        next(a.split("=", 1)[1] for a in args if a.startswith("-var-file="))
    )
    fixtures = json.loads(os.environ.get("MOCK_CHANGES", "{}"))
    if "-destroy" in args:
        fixtures = {**fixtures, "actions": ["delete"]}
    resource = {
        "mode": "managed",
        "type": "rediscloud_agent_memory",
        "address": 'module.agent_memory["shopping_agent"].rediscloud_agent_memory.this',
        "change": {
            "actions": fixtures.get("actions", ["no-op"]),
            "before": fixtures.get("before", {}),
            "after": fixtures.get("after", {}),
            "after_sensitive": fixtures.get("after_sensitive", {}),
            "after_unknown": {},
        },
    }
    plan = {
        "state_key": key,
        "resource_changes": fixtures.get("resources", [resource]),
        "output_changes": fixtures.get("output_changes", {}),
    }
    (
        stack / next(a.split("=", 1)[1] for a in args if a.startswith("-out="))
    ).write_text(json.dumps(plan))
elif command == "show":
    print((stack / args[-1]).read_text())
    sys.exit(0)
elif command == "apply":
    key = json.loads((stack / args[-1]).read_text())["state_key"]
else:
    raise SystemExit("Unexpected Terraform command: " + command)
with open(os.environ["MOCK_EVENTS"], "a") as f:
    f.write(json.dumps({"command": command, "state_key": key}) + "\n")
if command == "apply" and os.environ.get("MOCK_FAIL_APPLY"):
    sys.exit(2)
