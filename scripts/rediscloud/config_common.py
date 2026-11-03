"""Shared JSON checks and private input-file helpers."""

from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


MODE_VALUES = {"managed", "external"}


KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}[a-z0-9]$")


NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")


ENV_VAR_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


SENSITIVE_LITERAL_KEYS = {
    "api_key",
    "secret_key",
    "access_key",
    "password",
    "token",
    "provider_api_key",
    "acl_user_password_override",
}


class ConfigError(Exception):
    pass


def normalize_name(value: str) -> str:
    ascii_value = (
        unicodedata.normalize("NFKD", value.strip()).encode("ascii", "ignore").decode("ascii")
    )
    normalized = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower())
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return normalized


def unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate properties before they overwrite desired resources."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ConfigError(
                f"Duplicate JSON property {key!r}; configuration keys must be unique."
            )
        result[key] = value
    return result


def read_json(path: Path) -> dict[str, Any]:
    def reject_constant(value):
        raise ConfigError(f"{path}: non-finite JSON number {value} is not supported.")

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=unique_json_object,
            parse_constant=reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}: invalid JSON: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"{path}: cannot read file: {exc}") from exc

    if not isinstance(payload, dict):
        raise ConfigError("Config root must be a JSON object.")

    return payload


def fail_unknown_fields(path: str, obj: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(obj) - allowed)
    if unknown:
        raise ConfigError(f"{path}: unknown field(s): {', '.join(unknown)}")


def require_object(path: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{path} must be an object.")
    return value


def optional_object(path: str, value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    return require_object(path, value)


def require_string(path: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{path} must be a non-empty string.")
    return value


def get_mode(path: str, obj: dict[str, Any]) -> str:
    mode = obj.get("mode", "managed")
    if mode not in MODE_VALUES:
        raise ConfigError(f"{path}.mode must be one of: {', '.join(sorted(MODE_VALUES))}.")
    return mode


def validate_key(path: str, value: str) -> None:
    if not KEY_PATTERN.fullmatch(value):
        raise ConfigError(
            f"{path} must contain only lowercase letters, numbers, hyphens, or underscores, "
            "start and end with a letter or number, and be at most 64 characters."
        )


def validate_normalized_name(path: str, value: str) -> str:
    normalized = normalize_name(value)
    if not NAME_PATTERN.fullmatch(normalized):
        raise ConfigError(
            f"{path} normalizes to {normalized!r}, but it must become a lowercase, "
            "hyphen-separated name that is 3 to 63 characters long."
        )
    return normalized


def walk_sensitive_literals(path: str, value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            if key in SENSITIVE_LITERAL_KEYS and child not in (None, ""):
                raise ConfigError(
                    f"{child_path} looks like a secret literal. Store secret values outside git and use secret_ref."
                )
            walk_sensitive_literals(child_path, child)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            walk_sensitive_literals(f"{path}[{index}]", child)


def compact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: compact(child) for key, child in value.items() if child is not None}
    if isinstance(value, list):
        return [compact(child) for child in value]
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        # Rendered inputs can contain model credentials, including in local runs.
        os.fchmod(stream.fileno(), 0o600)
        stream.write(json.dumps(compact(payload), indent=2, sort_keys=True) + "\n")


def copy_fields(source: dict[str, Any], field_names: set[str]) -> dict[str, Any]:
    return {field: source[field] for field in sorted(field_names) if field in source}


def validate_env_var_name(path: str, value: str) -> None:
    if not ENV_VAR_PATTERN.fullmatch(value):
        raise ConfigError(f"{path} must be a valid environment variable name.")
