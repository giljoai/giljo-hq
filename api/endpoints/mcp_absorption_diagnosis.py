# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
MCP absorbed-argument diagnosis -- TSK-9309 / BE-9348 / TSK-9450.

INF-9463: split out of ``api.endpoints.mcp_transport`` verbatim (pure motion,
no behaviour change) once that module reached the 800-line file cap with zero
headroom left. This block has no shared state and no transport imports of its
own; its only external caller is the single import in ``mcp_sdk_server.py``.

Diagnoses a caller's tool-call serialization merging one argument into the
string value of a neighbouring one, so a missing (or silently absorbed)
argument gets an agent-actionable rejection naming the real cause instead of
a bare "field required" that sends the caller off to fix the wrong thing.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, NamedTuple


# ---------------------------------------------------------------------------
# TSK-9309: absorbed-argument diagnosis.
#
# A caller's tool-call serialization can merge one argument into the string value
# of a neighbouring one: the following argument never leaves the caller, and the
# server sees a payload genuinely missing a required field. The bare pydantic
# "key_outcomes / Field required" that results is TRUE about the payload received
# and WRONG about the cause — it sends the caller off to rewrite an argument it
# supplied correctly, at the cost of repeated failed retries.
#
# Measured, so the diagnosis below is not guesswork: the FastMCP argument boundary
# validates a 180 KB payload with the field intact, and _read_full_body/
# _replay_receive replay 2 MB byte-identically in one frame and in 17-byte frames.
# Nothing server-side drops the field, and there is no cap to raise.
#
# BE-9348 widened this. It no longer runs ONLY once a required argument is absent:
# when absorption swallows an OPTIONAL argument, every required one is still present,
# the call is ACCEPTED, and the residue is persisted verbatim — the same defect with
# no error at all. So the scan now runs on well-formed-looking calls too, and it CAN
# refuse one. That is a deliberate trade, and it is what the two extra conditions on
# the nothing-missing path exist to bound: conclusive evidence only, plus a tail that
# is pure call syntax AND carries an actual serialized value.
# ---------------------------------------------------------------------------

# Unparsed tool-call markup sitting inside a string value: the caller's own call
# syntax, which no legitimate prose argument contains.
_TOOLCALL_MARKUP_RESIDUE = re.compile(r"</\w*:?invoke>|<parameter\s+name=", re.IGNORECASE)

# The named form of that markup, used to recover WHICH argument was absorbed so the
# rejection can name it (BE-9348).
_PARAMETER_NAME_TAG = re.compile(r"<parameter\s+name=\"(\w+)\"", re.IGNORECASE)

# The tail of an absorbed JSON list ('..."]'), left behind when a list-valued
# argument is swallowed into the preceding string.
_ABSORBED_ARRAY_TAIL = ('"]', "']")

# Structural leftovers of a serialized tool call: tags, quoted strings, and JSON
# punctuation. What survives stripping these from a tail is ordinary prose.
_MARKUP_TAG = re.compile(r"<[^>]*>")
_QUOTED_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')
_JSON_PUNCTUATION = re.compile(r"[\[\]{}:,\s]")

# The opening character of a STRUCTURED argument value ('["docs", "chore"]'). A bare
# angle-bracket PLACEHOLDER in ordinary prose ("Usage: giljo close <project_id>") leaves
# nothing once the tag is stripped. Without this, stripping the tag alone reduces the
# placeholder to empty and the tail reads as "pure call syntax" with no absorbed value
# present at all — which refused ordinary sentences across 117 parameter names, among
# them 'name', 'title', 'status' and 'description'.
_VALUE_OPENER = re.compile(r"[\[{\"]")

# A bare JSON scalar ('3', 'true', 'null'). An absorbed argument does NOT always bring a
# bracket: a scalar-valued parameter leaves a bare token behind, and 15 string->scalar
# adjacencies exist on the live surface (e.g. spawn_job mission->phase). The scalar
# allowance is gated on the serializer's own <parameter name="..."> markup — NOT because
# prose cannot contain that markup (it demonstrably can: post_to_thread.content,
# spawn_job.mission and write_memory_entry.summary all legitimately quote it), but
# because the gate is strictly cheaper there. Ungated, a bare digit would refuse
# "…<project_id> 2026"; gated, the refusals are confined to text that already carries
# the harness's own call syntax.
_JSON_SCALAR = re.compile(r"\b(?:true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
_VALUE_TOKEN = re.compile(r"[\[{\"]|\b(?:true|false|null)\b|-?\d")


class _Residue(NamedTuple):
    """Evidence that a string argument absorbed a following one.

    ``absorbed`` is the parameter name the residue names when it can be recovered
    (``None`` when the markup is anonymous, e.g. a bare ``</invoke>``). ``start`` is
    where the residue begins, so the tail after it can be examined.
    """

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
    """Describe the evidence that ``value`` absorbed a following argument, else ``None``.

    Markup residue and an inline parameter tag are the caller's own call syntax sitting
    inside a string value, which no legitimate prose contains — those are conclusive. A
    bare JSON-list tail is suggestive but not proof: a summary CAN legitimately end that
    way. TSK-9309b keeps that signal (it costs nothing on an already-failing call) but
    the caller is told so, because asserting a cause on the weakest evidence available is
    a smaller version of the defect this whole diagnosis exists to correct.

    BE-9348: ``self_param`` is skipped when matching inline tags. A value that contains
    its OWN closing tag says nothing about a FOLLOWING argument, and treating it as
    evidence produced advice as useless as "re-send with a shorter 'project_id'" for a
    64-character UUID.
    """
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
    """True when the tail is leftover call syntax AND carries a serialized value.

    Absorption appends a serialized argument and stops, so what follows the residue is
    a tag, then a JSON value, then nothing. Two things must both hold, and the second
    is not redundant:

    1. Nothing but markup, quoted strings and JSON punctuation survives to
       end-of-string. Prose that merely QUOTES markup keeps talking afterwards and
       fails here.
    2. A serialized value is actually present. Stripping ``<project_id>`` from
       "Usage: giljo close <project_id>" leaves an empty string, which satisfies (1)
       vacuously — so condition (1) ALONE refused ordinary prose containing an
       angle-bracket placeholder. There are 117 distinct parameter names across the
       tool surface, including 'name', 'title', 'status' and 'description', so that
       was not a corner case but "a developer wrote a placeholder in a sentence".

    Checking only that something survives the tag strip is not enough either: a
    trailing "<name>," leaves a lone comma, which JSON punctuation then removes. The
    test is therefore for a VALUE, which a placeholder never carries.

    A value is NOT always bracketed. A scalar-valued parameter is absorbed as a bare
    token ('<parameter name="phase">3'), and 15 string->scalar adjacencies exist on the
    live surface. The scalar allowance is gated on the serializer's own
    ``<parameter name="...">`` markup, which narrows it but does NOT make it exact:

        Confirmed the residue shape: <parameter name="requires_action">true
        Status update: worker mid-task.<parameter name="requires_action">true

    have BYTE-IDENTICAL tails. No tail-based gate can separate them, because the
    distinguishing information is not in the tail. Legitimate prose CAN contain this
    markup — ``post_to_thread.content``, ``spawn_job.mission`` and
    ``write_memory_entry.summary`` all quote it — so the gate is a cost reduction, not a
    proof. Ungated, a bare digit would additionally refuse "…<project_id> 2026".

    The residual is therefore real and accepted: text ending mid-air on raw markup with
    no terminal punctuation is refused (a trailing period, backtick or quote makes it
    pass). That is tolerable only because refusal is RECOVERABLE and silent persistence
    is not — the message names the parameter and states nothing was written, so the
    caller rewords and proceeds.
    """
    without_tags = _MARKUP_TAG.sub(" ", tail)
    scalars_are_credible = _PARAMETER_NAME_TAG.search(tail) is not None
    if not (_VALUE_TOKEN if scalars_are_credible else _VALUE_OPENER).search(without_tags):
        return False
    stripped = _QUOTED_STRING.sub(" ", without_tags)
    if scalars_are_credible:
        stripped = _JSON_SCALAR.sub(" ", stripped)
    return _JSON_PUNCTUATION.sub("", stripped) == ""


# TSK-9450: shared remedy. The old "send a SHORTER '{param}'" does not work and contradicted this
# message's own "no payload limit was reached" -- absorption eats what FOLLOWS the field, so the
# variable is order, not size. Why + measurements: tests/integration/test_tsk9450_absorption_remedy_wording_mcp_boundary.py
_REORDER_REMEDY = (
    "so making '{param}' shorter will NOT help. Re-send the call with '{param}' as the LAST argument -- "
    "the absorption swallows whatever follows it, so with nothing after it {kept} arrives as its own argument."
)


def _absorbed_required_message(
    tool_name: str, param: str, value: str, residue: _Residue, missing: Sequence[str]
) -> str:
    """TSK-9309's rejection: a required argument is absent because a neighbour ate it."""
    missing_list = ", ".join(repr(field) for field in missing)
    # Confident wording only where the evidence is conclusive; otherwise the
    # message states a possibility, so the caller is not sent to fix the wrong
    # thing on a hunch.
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
    """BE-9348's rejection: nothing REQUIRED is missing, so this call would otherwise
    have succeeded and written the caller's raw markup into the permanent record."""
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
    """Return an agent-actionable rejection naming the real cause, or ``None``.

    ``None`` means "no absorption evidence" — the caller simply omitted the field,
    and the ordinary validation error is the honest answer. Returning a message
    here would repeat the original defect in the opposite direction: naming a
    cause that is not the real one.

    BE-9348: the scan is no longer gated on a required argument already being absent.
    When absorption swallows an OPTIONAL argument, every required one is still present,
    validation passes, and the residue is PERSISTED — the same defect with no error at
    all, which is strictly worse. That path is the only one here that can turn a
    currently-succeeding call into a rejection, so it is held to two extra conditions:
    the evidence must be conclusive (never the weak JSON-list tail), and the tail after
    the residue must be pure call syntax.
    """
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
        # The residue must name an argument THIS tool actually has. When it does not
        # (e.g. '<parameter name="phase">' on write_project_closeout), `absorbed` is
        # already None and the rejection would claim "a later optional argument was
        # absorbed" -- false, because the tool has no such argument to lose. On a change
        # whose whole risk axis is false positives, refusing to guess is free.
        if residue.absorbed is None:
            continue
        if not _tail_is_pure_call_syntax(value[residue.start :]):
            continue
        return _absorbed_optional_message(tool_name, param, value, residue)
    return None
