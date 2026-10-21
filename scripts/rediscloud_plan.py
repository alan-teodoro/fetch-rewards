#!/usr/bin/env python3
"""Inspect dependency availability from a saved Terraform JSON plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from rediscloud.terraform import dependency_status


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check whether a planned dependency is available for downstream name lookups."
    )
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument(
        "--resource-type",
        required=True,
        choices=["rediscloud_subscription", "rediscloud_subscription_database"],
    )
    args = parser.parse_args()
    try:
        print(dependency_status(json.loads(args.plan.read_text()), args.resource_type))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Cannot determine dependency status: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
