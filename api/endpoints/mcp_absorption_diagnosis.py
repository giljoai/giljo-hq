# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, NamedTuple



_TOOLCALL_MARKUP_RESIDUE = re.compile(r"</\w*:?invoke>|<parameter\s+name=", re.IGNORECASE)

_PARAMETER_NAME_TAG = re.compile(r"<parameter\s+name=\"(\w+)\"", re.IGNORECASE)

_ABSORBED_ARRAY_TAIL = ('"]', "']")

_MARKUP_TAG = re.compile(r"<[^>]*>")
_QUOTED_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')
_JSON_PUNCTUATION = re.compile(r"[\[\]{}:,\s]")

_VALUE_OPENER = re.compile(r"[\[{\"]")

_JSON_SCALAR = re.compile(r"\b(?:true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
_VALUE_TOKEN = re.compile(r"[\[{\"]|\b(?:true|false|null)\b|-?\d")


class _Residue(NamedTuple):

    description: str
    conclusive: bool
    absorbed: str | None
    start: int


def _absorption_residue(
    value: str,
    parameter_names: Iterable[str],
    *,
    self_param: str | None = None,
) -> _Residue | None:
    match = _TOOLCALL_MARKUP_RESIDUE.search(value)
    if match:
        named = _PARAMETER_NAME_TAG.search(value)
        absorbed = named.group(1) if named else None
        if absorbed is not None and (absorbed == self_param or absorbed not in parameter_names):
            absorbed = None
        return _Residue(
            description="unparsed tool-call markup",
            conclusive=True,
            absorbed=absorbed,
            start=match.start(),
        )
    for param in parameter_names:
        if param == self_param:
            continue
        for tag in (f"</{param}>", f"<{param}>"):
            index = value.find(tag)
            if index != -1:
                return _Residue(
                    description=f"an inline '{param}' tag",
                    conclusive=True,
                    absorbed=param,
                    start=index,
                )
    if value.rstrip().endswith(_ABSORBED_ARRAY_TAIL):
        return _Residue(
            description="the tail of an unterminated JSON list",
            conclusive=False,
            absorbed=None,
            start=len(value),
        )
    return None


def _tail_is_pure_call_syntax(tail: str) -> bool:
    without_tags = _MARKUP_TAG.sub(" ", tail)
    scalars_are_credible = _PARAMETER_NAME_TAG.search(tail) is not None
    if not (_VALUE_TOKEN if scalars_are_credible else _VALUE_OPENER).search(without_tags):
        return False
    stripped = _QUOTED_STRING.sub(" ", without_tags)
    if scalars_are_credible:
        stripped = _JSON_SCALAR.sub(" ", stripped)
    return _JSON_PUNCTUATION.sub("", stripped) == ""


_REORDER_REMEDY = (
    "so making '{param}' shorter will NOT help. Re-send the call with '{param}' as the LAST argument -- "
    "the absorption swallows whatever follows it, so with nothing after it {kept} arrives as its own argument."
)


def _absorbed_required_message(
    tool_name: str, param: str, value: str, residue: _Residue, missing: Sequence[str]
) -> str:
    missing_list = ", ".join(repr(field) for field in missing)
    claim = (
        f"{missing_list} was absorbed into '{param}' by the caller's tool-call serialization "
        f"and never arrived as a separate argument"
        if residue.conclusive
        else (
            f"{missing_list} MAY have been absorbed into '{param}' by the caller's tool-call "
            f"serialization rather than genuinely omitted -- that tail is suggestive, not proof, "
            f"so check whether '{param}' ends with content that belongs to {missing_list}"
        )
    )
    return (
        f"Tool '{tool_name}' arrived without required argument(s) {missing_list}, but its "
        f"'{param}' argument is {len(value)} characters long and ends with {residue.description}. "
        f"{claim} -- the field itself is not wrong, and no server-side payload limit was reached "
        f"(every field was within its documented cap), "
        f"{_REORDER_REMEDY.format(param=param, kept=missing_list)} Nothing was written."
    )


def _absorbed_optional_message(tool_name: str, param: str, value: str, residue: _Residue) -> str:
    absorbed = f"'{residue.absorbed}'" if residue.absorbed else "a later optional argument"
    return (
        f"Tool '{tool_name}' arrived with every required argument present, but its '{param}' "
        f"argument is {len(value)} characters long and contains {residue.description}, after which "
        f"nothing but tool-call syntax follows. {absorbed} was absorbed into '{param}' by the "
        f"caller's tool-call serialization and never arrived as its own argument -- so this call "
        f"would have been ACCEPTED, {absorbed} silently dropped, and the raw markup stored verbatim "
        f"in the permanent record. No server-side payload limit was reached (every field was within "
        f"its documented cap), {_REORDER_REMEDY.format(param=param, kept=absorbed)} Nothing was written."
    )


def describe_absorbed_argument(
    *,
    tool_name: str,
    arguments: Mapping[str, Any],
    required: Sequence[str],
    parameter_names: Sequence[str],
) -> str | None:
    missing = [field for field in required if field not in arguments]
    for param in parameter_names:
        value = arguments.get(param)
        if not isinstance(value, str):
            continue
        residue = _absorption_residue(value, parameter_names, self_param=param)
        if residue is None:
            continue
        if missing:
            return _absorbed_required_message(tool_name, param, value, residue, missing)
        if not residue.conclusive:
            continue
        if residue.absorbed is None:
            continue
        if not _tail_is_pure_call_syntax(value[residue.start :]):
            continue
        return _absorbed_optional_message(tool_name, param, value, residue)
    return None
