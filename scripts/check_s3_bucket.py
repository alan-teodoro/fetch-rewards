#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys


def main() -> None:
    query = json.load(sys.stdin)
    bucket_name = str(query.get("bucket_name", "")).strip()

    if not bucket_name:
        print(json.dumps({"error": "bucket_name is required"}))
        sys.exit(1)

    result = subprocess.run(
        ["aws", "s3api", "head-bucket", "--bucket", bucket_name],
        check=False,
        capture_output=True,
        text=True,
    )

    combined = f"{result.stdout or ''}\n{result.stderr or ''}".lower()
    exists = result.returncode == 0 or "403" in combined or "forbidden" in combined

    print(json.dumps({"exists": "true" if exists else "false"}))


if __name__ == "__main__":
    main()
