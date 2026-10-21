#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_BASE_DEFAULT = "https://api.redislabs.com/v1"
USER_AGENT = "rediscloud-github-actions-automation/1.0"


def api_get(path: str, api_base: str, headers: dict[str, str], params: dict[str, Any] | None = None) -> Any:
    query = f"?{urlencode(params)}" if params else ""
    request = Request(f"{api_base.rstrip('/')}{path}{query}", headers=headers)
    with urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def walk(node: Any) -> Iterable[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)


def extract_subscriptions(payload: Any) -> list[dict[str, str]]:
    subscriptions = []
    seen = set()

    for item in walk(payload):
        subscription_id = item.get("subscriptionId") or item.get("id")
        name = item.get("name")
        if not subscription_id or not name:
            continue
        if item.get("databaseId") or item.get("datasetSizeInGb") is not None:
            continue

        key = str(subscription_id)
        if key in seen:
            continue

        seen.add(key)
        subscriptions.append({"id": key, "name": str(name)})

    return subscriptions


def extract_databases(payload: Any) -> list[dict[str, str]]:
    databases = []
    seen = set()

    for item in walk(payload):
        database_id = item.get("databaseId") or item.get("dbId")
        name = item.get("name")
        if not database_id or not name:
            continue

        key = str(database_id)
        if key in seen:
            continue

        seen.add(key)
        databases.append({"id": key, "name": str(name)})

    return databases


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
        details = f"{details}. Check Redis Cloud API key permissions."

    return details


def write_outputs(outputs: dict[str, Any]) -> None:
    github_output = os.getenv("GITHUB_OUTPUT")
    if github_output:
        with Path(github_output).open("a", encoding="utf-8") as handle:
            for key, value in outputs.items():
                handle.write(f"{key}={value}\n")
    else:
        print(json.dumps(outputs, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Look up Redis Cloud subscription and database names.")
    parser.add_argument("--subscription-name", required=True)
    parser.add_argument("--database-name")
    parser.add_argument("--allow-missing-subscription", action="store_true")
    parser.add_argument("--api-base", default=API_BASE_DEFAULT)
    args = parser.parse_args()

    access_key = os.getenv("REDISCLOUD_ACCESS_KEY")
    secret_key = os.getenv("REDISCLOUD_SECRET_KEY")
    if not access_key or not secret_key:
        print("REDISCLOUD_ACCESS_KEY and REDISCLOUD_SECRET_KEY must be set.", file=sys.stderr)
        sys.exit(1)

    headers = {
        "x-api-key": access_key,
        "x-api-secret-key": secret_key,
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }

    try:
        subscriptions_payload = api_get("/subscriptions", args.api_base, headers, {"offset": 0, "limit": 100})
    except HTTPError as exc:
        print(f"Failed to query Redis Cloud subscriptions: {describe_http_error(exc)}", file=sys.stderr)
        sys.exit(1)
    except URLError as exc:
        print(f"Failed to query Redis Cloud subscriptions: {exc}", file=sys.stderr)
        sys.exit(1)

    subscriptions = extract_subscriptions(subscriptions_payload)
    subscription = next((item for item in subscriptions if item["name"] == args.subscription_name), None)

    if not subscription:
        write_outputs(
            {
                "subscription_exists": "false",
                "subscription_id": "",
                "database_exists": "false",
                "database_id": "",
                "subscription_database_count": "0",
                "subscription_database_names": "",
            }
        )

        if args.allow_missing_subscription:
            print(f'Subscription "{args.subscription_name}" was not found. The workflow will create it.')
            sys.exit(0)

        known_names = ", ".join(sorted(item["name"] for item in subscriptions)) or "none returned by Redis Cloud"
        print(f'Subscription "{args.subscription_name}" was not found.', file=sys.stderr)
        print("Check the spelling or use the database workflow to create the subscription first.", file=sys.stderr)
        print(f"Known subscriptions: {known_names}", file=sys.stderr)
        sys.exit(1)

    try:
        databases_payload = api_get(
            f"/subscriptions/{subscription['id']}/databases",
            args.api_base,
            headers,
            {"offset": 0, "limit": 100},
        )
    except HTTPError as exc:
        if exc.code == 404:
            databases_payload = []
        else:
            print(f"Failed to query Redis Cloud databases: {describe_http_error(exc)}", file=sys.stderr)
            sys.exit(1)
    except URLError as exc:
        print(f"Failed to query Redis Cloud databases: {exc}", file=sys.stderr)
        sys.exit(1)

    databases = extract_databases(databases_payload)
    database = next((item for item in databases if item["name"] == args.database_name), None) if args.database_name else None

    write_outputs(
        {
            "subscription_exists": "true",
            "subscription_id": subscription["id"],
            "database_exists": str(database is not None).lower(),
            "database_id": database["id"] if database else "",
            "subscription_database_count": str(len(databases)),
            "subscription_database_names": ",".join(sorted(item["name"] for item in databases)),
        }
    )


if __name__ == "__main__":
    main()
