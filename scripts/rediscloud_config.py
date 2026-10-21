#!/usr/bin/env python3
"""Validate and render Redis Cloud subscription configuration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from rediscloud.config_common import ConfigError, get_mode, read_json as read_json
from rediscloud.config import (
    load_and_validate,
    render,
    select_destroy_config,
    validate_workflow_path,
)


def validate_command(args: argparse.Namespace) -> None:
    config = load_and_validate(args.config)
    print(
        json.dumps(
            {
                "valid": True,
                "customer": config["customer"],
                "environment": config["environment"],
                "subscription_key": config["subscription_key"],
                "subscription_name": config["_normalized"]["subscription_name"],
                "databases": len(config.get("databases", {})),
                "agent_memory_stores": len(config.get("agent_memory_stores", {})),
            },
            indent=2,
            sort_keys=True,
        )
    )


def render_command(args: argparse.Namespace) -> None:
    manifest = render(args.config, args.out_dir)
    print(json.dumps(manifest, indent=2, sort_keys=True))


def validate_destroy_command(args: argparse.Namespace) -> None:
    config = select_destroy_config(load_and_validate(args.config), args.agent_memory_key)
    print(
        json.dumps(
            {
                "valid": True,
                "destroy_scope": "agent_memory"
                if args.agent_memory_key
                else "all_managed_resources",
                "agent_memory_keys": [
                    key
                    for key, store in config.get("agent_memory_stores", {}).items()
                    if get_mode(key, store) == "managed"
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )


def render_destroy_command(args: argparse.Namespace) -> None:
    print(
        json.dumps(
            render(args.config, args.out_dir, destroy=True, agent_memory_key=args.agent_memory_key),
            indent=2,
            sort_keys=True,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate and render Redis Cloud subscription config files."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate a subscription config file.")
    validate_parser.add_argument("--config", required=True, type=Path)
    validate_parser.add_argument(
        "--workflow", action="store_true", help="Require a repository configuration path."
    )
    validate_parser.set_defaults(func=validate_command)

    render_parser = subparsers.add_parser(
        "render", help="Render Terraform tfvars and a manifest from a config file."
    )
    render_parser.add_argument("--config", required=True, type=Path)
    render_parser.add_argument("--out-dir", required=True, type=Path)
    render_parser.set_defaults(func=render_command)

    validate_destroy_parser = subparsers.add_parser(
        "validate-destroy", help="Validate the complete config or an Agent Memory key for destroy."
    )
    validate_destroy_parser.add_argument("--config", required=True, type=Path)
    validate_destroy_parser.add_argument("--agent-memory-key", default=None)
    validate_destroy_parser.add_argument("--workflow", action="store_true")
    validate_destroy_parser.set_defaults(func=validate_destroy_command)

    render_destroy_parser = subparsers.add_parser(
        "render-destroy",
        help="Render all managed resources or only one Agent Memory stack for destroy.",
    )
    render_destroy_parser.add_argument("--config", required=True, type=Path)
    render_destroy_parser.add_argument("--out-dir", required=True, type=Path)
    render_destroy_parser.add_argument("--agent-memory-key", default=None)
    render_destroy_parser.set_defaults(func=render_destroy_command)

    args = parser.parse_args()
    try:
        if getattr(args, "workflow", False):
            validate_workflow_path(args.config)
        args.func(args)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
