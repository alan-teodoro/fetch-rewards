#!/usr/bin/env python3
"""Review Terraform changes, then execute the approved encrypted bundle."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tarfile

from rediscloud.bundles import load_bundle
from rediscloud.lifecycle import plan_phase, apply_phase
from rediscloud.stacks import STACKS


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["plan", "load", "apply"])
    parser.add_argument(
        "--phase", required=True, choices=[*sorted(STACKS), "preview", "destroy", "rollout"]
    )
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--key")
    parser.add_argument("--sha256")
    args = parser.parse_args()
    try:
        {"plan": plan_phase, "load": load_bundle, "apply": apply_phase}[args.command](args)
    except (
        ValueError,
        KeyError,
        OSError,
        subprocess.CalledProcessError,
        tarfile.TarError,
    ) as error:
        print(f"Reviewed Terraform execution stopped: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
