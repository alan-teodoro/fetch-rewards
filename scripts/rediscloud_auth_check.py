#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_BASE_DEFAULT = "https://api.redislabs.com/v1"
USER_AGENT = "rediscloud-github-actions-automation/1.0"


def describe_http_error(exc: HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8").strip()
    except Exception:
        body = ""

    details = f"HTTP {exc.code}"
    if body:
        details = f"{details}: {body}"
    elif exc.reason:
        details = f"{details}: {exc.reason}"

    if exc.code in {401, 403}:
        details = (
            f"{details}. Check REDISCLOUD_ACCESS_KEY and REDISCLOUD_SECRET_KEY, "
            "Redis Cloud API permissions, and any Redis Cloud API IP allowlist."
        )

    return details


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Redis Cloud API credentials.")
    parser.add_argument("--api-base", default=API_BASE_DEFAULT)
    args = parser.parse_args()

    access_key = os.getenv("REDISCLOUD_ACCESS_KEY")
    secret_key = os.getenv("REDISCLOUD_SECRET_KEY")
    if not access_key or not secret_key:
        print("REDISCLOUD_ACCESS_KEY and REDISCLOUD_SECRET_KEY must be set.", file=sys.stderr)
        sys.exit(1)

    params = urlencode({"offset": 0, "limit": 1})
    request = Request(
        f"{args.api_base.rstrip('/')}/subscriptions?{params}",
        headers={
            "x-api-key": access_key,
            "x-api-secret-key": secret_key,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )

    try:
        with urlopen(request) as response:
            json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        print(f"Redis Cloud credential validation failed: {describe_http_error(exc)}", file=sys.stderr)
        sys.exit(1)
    except URLError as exc:
        print(f"Redis Cloud credential validation failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print("Redis Cloud API credentials validated.")


if __name__ == "__main__":
    main()
