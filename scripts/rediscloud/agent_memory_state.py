"""Translate stored Agent Memory blocks into deletion-only stack inputs."""

from copy import deepcopy


def optional_state_block(value, path):
    # Current provider blocks are zero-or-one lists; older builds used objects.
    if value is None or value == []:
        return None
    if isinstance(value, dict):
        return deepcopy(value)
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
        return deepcopy(value[0])
    raise ValueError(f"Omitted state has an invalid {path} block; reconcile manually.")


def memory_types_from_state(values):
    if not isinstance(values, list) or any(
        not isinstance(item, dict) for item in values
    ):
        raise ValueError(
            "Omitted state has invalid custom memory types; reconcile manually."
        )
    result = deepcopy(values)
    for item in result:
        item["extraction_strategy"] = optional_state_block(
            item.get("extraction_strategy"), "custom_memory_types.extraction_strategy"
        )
    return result


def summarization_from_state(value):
    result = optional_state_block(value, "summarization")
    if result is not None:
        result["event_count"] = optional_state_block(
            result.get("event_count"), "summarization.event_count"
        )
    return result


def exclusions_from_state(value):
    result = optional_state_block(value, "long_term_memory_exclusions")
    if result is None:
        return None
    for name in ("semantic", "built_in_detectors", "custom_detectors"):
        result[name] = optional_state_block(
            result.get(name), f"long_term_memory_exclusions.{name}"
        )
    custom = result["custom_detectors"]
    if custom is not None:
        detectors = custom.get("detectors") or []
        if not isinstance(detectors, list) or any(
            not isinstance(item, dict) for item in detectors
        ):
            raise ValueError(
                "Omitted state has invalid custom detectors; reconcile manually."
            )
        for detector in detectors:
            matcher = optional_state_block(
                detector.get("matcher"), "custom_detectors.matcher"
            )
            detector["matcher"] = matcher
            if matcher is not None:
                matcher["regex"] = optional_state_block(
                    matcher.get("regex"), "matcher.regex"
                )
    return result


def agent_destroy_variables(values, name, database_id):
    result = {"agent_memory_name": name, "database_id": database_id}
    for field in (
        "short_term_ttl_seconds",
        "long_term_ttl_seconds",
        "extraction_cadence_seconds",
        "extraction_strategy",
    ):
        if values.get(field) is not None:
            result[field] = deepcopy(values[field])
    for field, convert in (
        ("custom_memory_types", memory_types_from_state),
        ("summarization", summarization_from_state),
        ("long_term_memory_exclusions", exclusions_from_state),
    ):
        if values.get(field) is not None:
            result[field] = convert(values[field])
    if values.get("timeouts") is not None:
        result["timeouts"] = optional_state_block(values["timeouts"], "timeouts")

    models = {
        block: optional_state_block(values.get(block), block)
        for block in ("llm", "embedding")
    }
    if any(model is not None for model in models.values()):
        if not all(model is not None for model in models.values()):
            raise ValueError(
                "Omitted state has incomplete customer-managed model configuration; reconcile manually."
            )
        for block, model in models.items():
            if not all(
                isinstance(model.get(field), str) and model[field].strip()
                for field in ("provider", "model")
            ):
                raise ValueError(
                    "Omitted state lacks model identity; reconcile manually."
                )
            result[block] = {
                "provider": model["provider"],
                "model": model["model"],
                "credentials": {"type": "apiKey"},
            }
            # The runner rejects non-deletion plans before these placeholders can be applied.
            result[block + "_api_key"] = "unused-during-destroy"
    return result
