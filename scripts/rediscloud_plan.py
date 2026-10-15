#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def dependency_status(plan: dict, resource_type: str) -> str:
    resources = [
        item for item in plan.get("resource_changes", [])
        if item.get("mode", "managed") == "managed" and item.get("type") == resource_type
    ]
    if len(resources) != 1:
        raise ValueError(f"Expected exactly one managed {resource_type} resource in the plan.")
    change = resources[0]["change"]
    if any(action in {"create", "delete"} for action in change["actions"]):
        return "pending"
    before = change.get("before") or {}
    after = change.get("after") or {}
    if (change.get("after_unknown") or {}).get("name") or before.get("name") != after.get("name"):
        return "pending"
    return "ready"


def main() -> None:
    parser = argparse.ArgumentParser(description="Check whether a planned dependency is available for downstream name lookups.")
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--resource-type", required=True, choices=["rediscloud_subscription", "rediscloud_subscription_database"])
    args = parser.parse_args()
    try:
        print(dependency_status(json.loads(args.plan.read_text()), args.resource_type))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Cannot determine dependency status: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
