#!/usr/bin/env python3
"""Simulate aws for workflow regressions using local files only."""

import os
import pathlib
import shutil
import sys

args = sys.argv[1:]
command = args[1]
if command == "list-objects-v2":
    import json

    if os.environ.get("MOCK_INVENTORY_FAILURE"):
        sys.exit(2)
    root = pathlib.Path(os.environ["MOCK_S3"])
    prefix = args[args.index("--prefix") + 1]
    print(
        json.dumps(
            {
                "Contents": [
                    {"Key": str(p.relative_to(root))}
                    for p in root.rglob("*")
                    if p.is_file() and str(p.relative_to(root)).startswith(prefix)
                ]
            }
        )
    )
    sys.exit(0)
key = args[args.index("--key") + 1]
path = pathlib.Path(os.environ["MOCK_S3"]) / key
if command == "put-object":
    assert args[args.index("--server-side-encryption") + 1] == "AES256"
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args[args.index("--body") + 1], path)
elif command == "get-object":
    shutil.copyfile(path, args[-1])
elif command == "delete-object":
    path.unlink(missing_ok=True)
else:
    raise SystemExit("Unsupported AWS mock")
