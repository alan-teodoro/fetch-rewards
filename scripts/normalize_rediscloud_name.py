#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import sys
import unicodedata


NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")


def normalize(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value.strip()).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower())
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return normalized


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize Redis Cloud resource names for Terraform-managed resources.")
    parser.add_argument("--field", required=True, help="Field name used in validation messages.")
    parser.add_argument("--value", required=True, help="Raw user-provided name.")
    args = parser.parse_args()

    normalized = normalize(args.value)
    if not NAME_PATTERN.fullmatch(normalized):
        print(
            f"{args.field} normalized to '{normalized}', but it must become a lowercase, "
            "hyphen-separated name that is 3 to 63 characters long.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(normalized)


if __name__ == "__main__":
    main()
