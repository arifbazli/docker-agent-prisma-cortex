"""Minimal JSON Schema validator (stdlib only).

Supports exactly these keywords:
    type, required, properties, additionalProperties, enum, pattern,
    items, minItems, minLength, uniqueItems
plus the annotation keywords $schema, $id, $comment, title, description
(ignored on purpose). Any other keyword raises UnsupportedKeyword, so a
schema can never be silently under-enforced.

`type` may be a string or a list of strings. `additionalProperties` may be
a boolean or a schema.

Usage:
    from jsonschema_lite import validate, ValidationError
    errors = validate(instance, schema)   # list of "path: message" strings
    check(instance, schema)               # raises ValidationError on first error
"""
from __future__ import annotations

import re

SUPPORTED = {
    "type", "required", "properties", "additionalProperties", "enum", "pattern",
    "items", "minItems", "minLength", "uniqueItems",
}
ANNOTATIONS = {"$schema", "$id", "$comment", "title", "description"}
TYPES = {"object", "array", "string", "integer", "number", "boolean", "null"}


class UnsupportedKeyword(ValueError):
    """The schema uses a keyword this validator does not implement."""


class ValidationError(ValueError):
    """The instance does not match the schema."""


def _is_type(value, name: str) -> bool:
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "null":
        return value is None
    raise UnsupportedKeyword(f"unknown type {name!r}")


def check_schema(schema, path: str = "#") -> None:
    """Raise UnsupportedKeyword if the schema uses anything not supported."""
    if not isinstance(schema, dict):
        raise UnsupportedKeyword(f"{path}: schema must be an object")
    for key, val in schema.items():
        if key in ANNOTATIONS:
            continue
        if key not in SUPPORTED:
            raise UnsupportedKeyword(f"{path}: unsupported keyword {key!r}")
        if key == "type":
            names = val if isinstance(val, list) else [val]
            for n in names:
                if n not in TYPES:
                    raise UnsupportedKeyword(f"{path}: unknown type {n!r}")
        elif key == "properties":
            for name, sub in val.items():
                check_schema(sub, f"{path}/properties/{name}")
        elif key == "items":
            check_schema(val, f"{path}/items")
        elif key == "additionalProperties" and isinstance(val, dict):
            check_schema(val, f"{path}/additionalProperties")
        elif key == "pattern":
            re.compile(val)


def _validate(inst, schema, path: str, errors: list) -> None:
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is_type(inst, n) for n in names):
            errors.append(f"{path}: expected {'/'.join(names)}, got {type(inst).__name__}")
            return
    if "enum" in schema and inst not in schema["enum"]:
        errors.append(f"{path}: {inst!r} not in {schema['enum']}")
    if isinstance(inst, str):
        if "minLength" in schema and len(inst) < schema["minLength"]:
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], inst):
            errors.append(f"{path}: {inst!r} does not match {schema['pattern']!r}")
    if isinstance(inst, list):
        if "minItems" in schema and len(inst) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if schema.get("uniqueItems"):
            seen = []
            for i, item in enumerate(inst):
                if item in seen:
                    errors.append(f"{path}/{i}: duplicate item {item!r}")
                seen.append(item)
        if "items" in schema:
            for i, item in enumerate(inst):
                _validate(item, schema["items"], f"{path}/{i}", errors)
    if isinstance(inst, dict):
        for name in schema.get("required", []):
            if name not in inst:
                errors.append(f"{path}: missing required property {name!r}")
        props = schema.get("properties", {})
        for name, val in inst.items():
            if name in props:
                _validate(val, props[name], f"{path}/{name}", errors)
            else:
                extra = schema.get("additionalProperties", True)
                if extra is False:
                    errors.append(f"{path}: unexpected property {name!r}")
                elif isinstance(extra, dict):
                    _validate(val, extra, f"{path}/{name}", errors)


def validate(instance, schema) -> list[str]:
    """Return a list of error strings (empty when valid). Raises
    UnsupportedKeyword if the schema itself uses unsupported keywords."""
    check_schema(schema)
    errors: list[str] = []
    _validate(instance, schema, "#", errors)
    return errors


def check(instance, schema) -> None:
    errors = validate(instance, schema)
    if errors:
        raise ValidationError("; ".join(errors[:10]) + (" ..." if len(errors) > 10 else ""))
