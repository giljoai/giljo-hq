# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from collections.abc import Iterable
from typing import Any


def nullable_enum_schema(values: list[str]):

    def _apply(schema: dict[str, Any]) -> None:
        for branch in schema["anyOf"]:
            if branch.get("type") == "string":
                branch["enum"] = list(values)

    return _apply


def enum_schema_without_default(values: list[str]):

    def _apply(schema: dict[str, Any]) -> None:
        schema["enum"] = list(values)
        schema.pop("default", None)

    return _apply


def _drop_title_metadata(schema: Any) -> None:
    if isinstance(schema, dict):
        if isinstance(schema.get("title"), str):
            del schema["title"]
        for value in schema.values():
            _drop_title_metadata(value)
    elif isinstance(schema, list):
        for value in schema:
            _drop_title_metadata(value)


def strip_schema_titles(tools: Iterable[Any]) -> None:
    for tool in tools:
        _drop_title_metadata(tool.parameters)
