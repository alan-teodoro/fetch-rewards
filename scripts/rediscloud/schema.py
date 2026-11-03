"""Validate the public configuration contract without resolving remote schemas."""

import json
from functools import lru_cache
from pathlib import Path

from .config_common import ConfigError


@lru_cache(maxsize=1)
def config_validator():
    try:
        from jsonschema import Draft202012Validator
    except ImportError as error:
        raise ConfigError(
            "Install Python dependencies with: python -m pip install -r requirements.txt"
        ) from error
    path = Path(__file__).resolve().parents[2] / "schemas/rediscloud-config.schema.json"
    schema = json.loads(path.read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_schema(config):
    error = next(config_validator().iter_errors(config), None)
    if error is None:
        return
    while error.context:
        # Nullable objects report an anyOf error at the parent; point at the invalid field.
        error = max(error.context, key=lambda child: len(child.absolute_path))
    path = "$"
    for part in error.absolute_path:
        path += f"[{part}]" if isinstance(part, int) else f".{part}"
    # ValidationError.message can contain the rejected value, including secret literals.
    if error.validator == "additionalProperties":
        unknown = sorted(set(error.instance) - set(error.schema.get("properties", {})))
        message = "contains unknown field(s): " + ", ".join(unknown)
    elif error.validator == "required":
        missing = [name for name in error.validator_value if name not in error.instance]
        path += "." + missing[0]
        message = "is required"
    elif error.validator == "type":
        types = error.validator_value
        message = "must be " + (types if isinstance(types, str) else " or ".join(types))
    else:
        message = "does not match the configuration schema"
    raise ConfigError(f"{path}: {message}. See schemas/rediscloud-config.schema.json.")
