#!/usr/bin/env python3
"""Simulate encrypted plan-bundle storage; raw state reads are forbidden."""

import os
import pathlib
import shutil
import sys

args = sys.argv[1:]
command = args[1]
assert command in {"put-object", "get-object", "delete-object"}, (
    "No state inventory commands are allowed"
)
key = args[args.index("--key") + 1]
assert "/review-plans/" in key and key.endswith(".tar.gz"), (
    "Scripts must not download Terraform state"
)
path = pathlib.Path(os.environ["MOCK_S3"]) / key
if command == "put-object":
    assert args[args.index("--server-side-encryption") + 1] == "AES256"
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args[args.index("--body") + 1], path)
elif command == "get-object":
    shutil.copyfile(path, args[-1])
else:
    path.unlink(missing_ok=True)
